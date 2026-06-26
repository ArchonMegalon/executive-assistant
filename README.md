# Executive Assistant

Executive Assistant is an operating system for one executive office: morning memos, decision queues, commitments, handoffs, approvals, and durable context across email, calendar, and selected messaging channels. This repository contains the product surface plus the runtime underneath it: a principal-scoped FastAPI control plane, a queue-backed execution plane, and a Postgres-backed context plane for approvals, human tasks, tools/connectors, observations, delivery, and memory.

## Product and runtime

- Product surface: marketing pages, onboarding, authenticated app shell, operator/admin shell, and optional public utility routes
- Control plane: API/auth/config, operator scripts, health/version endpoints, and runtime docs
- Execution plane: sessions, steps, queue leasing, approvals, human routing, and worker roles
- Context plane: memory, stakeholders, commitments, follow-ups, evidence, skills, and task contracts
- Durable source of truth: Postgres for sessions, steps, queue rows, approvals, outbox, and memory

## Core Product Boundary

The paying-customer product is intentionally narrow:

- one executive
- one operator
- Gmail + Calendar first
- one morning memo
- one decision queue
- one commitment system
- approvals and auditability

Default product mode is `EA_CORE`: the executive office loop. Memorial, provider lab, Chummer release control, and property are separate project modes, not implied EA-core product scope. See [PRODUCT_BOUNDARY.md](PRODUCT_BOUNDARY.md), `.codex-design/product/PROJECT_MODES.generated.json`, and `.codex-design/product/SHOW_SURFACE_MANIFEST.generated.json`.
For a live memorial runtime, run `make verify-memorial-deploy-readiness` first, then `make deploy-ea-memorial`; that path layers `docker-compose.memorial.yml`, sets the primary deploy mode to `MEMORIAL`, and keeps the deploy/runtime receipts aligned with what is actually mounted.
Default product mode does not mount experimental public utility routes such as `/results/*`, `/tours/*`, or `/memorials/*`. Those surfaces must be explicitly enabled for their own project mode and are not part of the core product story.
In `prod`, legacy authenticated runtime surfaces such as `/v1/memory/*`, `/v1/rewrite/*`, `/v1/channels/*`, and `/v1/responses*` are also off by default unless `EA_ENABLE_LEGACY_RUNTIME_SURFACES=1` is set deliberately.

## Run It

```bash
# Fresh host with Teable recovery:
export TEABLE_API_KEY='...'
make deploy-ea-prod

# Fallback without Teable recovery:
cp .env.example .env
# edit .env values, then rerun deploy
bash scripts/db_bootstrap.sh
```

Explicit Make deploy targets are split by product plane:

```bash
make deploy-ea-prod    # EA core/runtime services
make deploy-property   # PropertyQuarry isolated compose stack
```

The plain `make deploy` target is intentionally non-operational. Use `make deploy-ea-prod` or `make deploy-property` so an EA deploy cannot accidentally start the property stack.
`docker-compose.property.yml` follows the same default host posture as EA core: the API bind is loopback-only, and the property API/scheduler/database services are constrained with dropped capabilities, `no-new-privileges`, and bounded memory/PID limits.

GitHub Actions workflows are intentionally not tracked in this repo. The enforced replacement is the local gate surface in `Makefile`: `make ci-gates`, `make ci-gates-postgres`, `make ci-gates-postgres-legacy`, and `make release-preflight`.

Production startup now fails closed unless workspace-access token binding is anchored to a real public origin or explicit issuer. Set `EA_PUBLIC_APP_BASE_URL` or `EA_WORKSPACE_ACCESS_TOKEN_ISSUER`, and keep `EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE` plus `EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION` explicit in `.env` for durable cookie/session verification. In `prod`, placeholder or loopback binding origins such as `https://example.test`, `https://property.example.test`, or `http://localhost` are rejected.
`scripts/deploy.sh` now enforces the same rule before container startup: in `prod` it requires real production auth (`EA_API_TOKEN` or Cloudflare Access via `EA_CF_ACCESS_TEAM_DOMAIN` + `EA_CF_ACCESS_AUD`), requires a real `EA_SIGNING_SECRET`, refuses placeholder/loopback token-binding origins, and refuses missing or placeholder workspace token audience/key-version metadata.

The base compose profile now keeps host-mounted Docker and `/docker` access off by default. Add the host-tools override only for workflows that need host repo access or operator Docker control:

```bash
bash scripts/deploy.sh --compose-override docker-compose.host-tools.yml
```

That override does not hand the raw host socket to the runtime containers. It adds `ea-docker-socket-proxy`, mounts `/var/run/docker.sock` read-only only into that sidecar, constrains the sidecar itself with dropped capabilities, `no-new-privileges`, read-only rootfs, and bounded memory/PID limits, points the operator services at `DOCKER_HOST=tcp://ea-docker-socket-proxy:2375`, runs the operator image as its default non-root user, keeps `/docker` mounted read-only only on the operator image/profile, drops all ambient Linux capabilities, and applies bounded memory/PID limits plus `no-new-privileges` and read-only rootfs defaults to the operator services.
The base EA core compose also keeps its published ports loopback-only (`127.0.0.1:*`) and the prod override does not widen them. Public exposure is expected to go through an explicit ingress layer such as Cloudflare Tunnel, not a broad host-port bind.

To expose the stack through Cloudflare Tunnel, layer the tunnel override explicitly and set `EA_CF_TUNNEL_TOKEN` in your local `.env` first:

```bash
bash scripts/deploy.sh --compose-override docker-compose.cloudflared.yml
```

That tunnel sidecar is digest-pinned and constrained with dropped capabilities, `no-new-privileges`, and bounded memory/PID limits so public ingress does not bypass the runtime hardening posture.

Keep `PROPERTYQUARRY_TRUST_X_FORWARDED_HOST=0` unless the runtime is actually behind a trusted ingress that rewrites `X-Forwarded-Host`. Public canonicals, callback origins, and public-route host resolution now ignore forwarded-host headers by default.

`EA_ALLOW_LOOPBACK_NO_AUTH=1` is also fail-open only for local principal access. It no longer grants operator scope by itself; admin/operator surfaces still require an active operator profile for that principal.

`EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER=1` is now limited to loopback-local requests as well. It remains a local dev/test escape hatch, not a remote bearer-token impersonation feature.

Browser setup no longer supports caller-supplied principal switching at all when there is no bound access identity. The browser completes setup only for the deployment default workspace or the verified access-identity workspace.

`PROPERTYQUARRY_TRUST_X_FORWARDED_FOR=1` is also explicit now. Public rate-limit identity and other public IP-derived helpers use direct client host by default and only trust forwarded IP headers behind a deliberate ingress setup.

## Teable Environment Recovery

EA can rebuild its local environment from Teable after host loss. On a fresh host, seed only the Teable credential in the shell, then restore the root env, root local override env, service env, and referenced credential files:

```bash
export TEABLE_API_KEY='...'
# Optional when using a non-default Teable host:
export TEABLE_BASE_URL='https://app.teable.ai'
scripts/bootstrap_from_teable.sh
scripts/bootstrap_from_teable.sh --check
scripts/bootstrap_from_teable.sh --drill
scripts/bootstrap_from_teable.sh --ensure-local
scripts/bootstrap_from_teable.sh --fresh-host
scripts/bootstrap_from_teable.sh --probe
```

The restore script discovers the `ea_environment_secrets_recovery` table by name, so `EA_ENV_TEABLE_TABLE_ID` is not required on a fresh host. The default wrapper command restores and then returns one JSON result with bootstrap details, post-restore verification, and a redacted `recovery_proof` block with restored paths, counts, modes, and hash status but no secret values. Restore and bootstrap use the `EA_ENV_TEABLE_HOST_PROFILE` value, defaulting to `ea-prod`, so one recovery table can hold multiple host profiles without mixing restored values. Restore and bootstrap restore `.env`, `.env.local`, `ea/.env`, referenced local secret files such as `ONEMIN_DIRECT_API_KEYS_JSON_FILE`, and curated ignored local credential files matching `config/*.local.json` or `config/*client_secret*.json` when they were captured by backup.
Use `scripts/bootstrap_from_teable.sh --fresh-host` or `make env-fresh-host-teable` for the host-loss path: it requires `TEABLE_API_KEY` in the shell, ignores any need for `EA_ENV_TEABLE_TABLE_ID`, discovers the recovery table by name, restores live env/config artifacts, and verifies the restored hashes.
When `TEABLE_API_KEY` is seeded, `scripts/deploy.sh` and `make deploy-ea-prod` first run a Teable-backed local status check for `.env`, `.env.local`, `ea/.env`, and referenced credential files; they recover from Teable only when those local artifacts are missing, have the wrong owner-only mode, or no longer match the stored hashes. Without that seed, they keep the template fallback and stop for manual values when `.env` is absent.
When `recover` is pointed at a non-default env output tree, referenced secret files are restored under that same tree rather than the live repo paths.
Restore and bootstrap preserve any existing target env file or referenced secret file as a timestamped `.bak` next to the file before writing restored values.
Those `.bak` files contain secret material and are ignored by git; delete stale backups after confirming the restored files are healthy.
Restored env files and referenced secret files are written with owner-only permissions.
Restore and bootstrap fail before writing if Teable marks a value as present but the stored secret cell is blank.
Keep the recovery table current after changing local credentials:

```bash
make env-backup-teable
make verify-env-teable-recovery
make env-local-status-teable
make env-ensure-local-teable
make env-fresh-host-teable
make env-drill-teable
make env-check-teable
make env-probe-teable
make env-disable-extra-teable
```

Direct backup use must choose a value mode explicitly: `scripts/sync_env_to_teable.py backup --include-values` for disaster recovery, or `scripts/sync_env_to_teable.py backup --metadata-only` when refreshing env and referenced-file metadata without changing stored secret cells.
`scripts/bootstrap_from_teable.sh --check` or `make env-check-teable` runs table verification and a non-destructive drill, then removes the temporary drill directory when no explicit drill output path was provided.
`scripts/sync_env_to_teable.py local-status` or `make env-local-status-teable` verifies the current local env/config artifacts against Teable without writing anything.
`scripts/bootstrap_from_teable.sh --ensure-local` or `make env-ensure-local-teable` fixes mode-only drift in place and performs full recovery only when content is missing or mismatched.
`scripts/bootstrap_from_teable.sh --probe` or `make env-probe-teable` performs a fresh-host rehearsal: it clears the table-id argument, discovers the recovery table by name, restores into a throwaway private directory, verifies hashes, prints the recovery JSON, and removes the directory.
Verification fails with `extra_restorable_count` and sample `extra_restorable_keys` when same-profile Teable rows would restore but no longer appear in the current env files.
Verification also fails with `uncovered_local_secret_file_count` and sample `uncovered_local_secret_file_paths` when a likely local credential file in `config/` is present on disk but not covered by the recovery set.
Verification fails with `missing_required_env_file_count` when required default env files such as `.env` or `.env.local` are missing locally.
Verification fails with `missing_required_compose_env_count` when a non-defaulted Docker Compose `${VAR}` reference is not present in the Teable-recovered env set. Host-provided `HOME` is intentionally ignored.

Use `make env-disable-extra-teable` to set `restore_enabled=false` on stale same-profile rows without deleting their stored values, then rerun `make env-check-teable`. This target refuses to run while required default env files are missing, so a temporary local file loss cannot disable valid recovery rows.
`scripts/bootstrap_from_teable.sh --drill` or `make env-drill-teable` restores root env, service env, and referenced secret files into a private temporary directory and prints the directory path plus materialized referenced-file paths. It does not overwrite the live `.env` files. The drill directory contains secret material; delete it after inspection.
Drill output includes `drill_verification`, which checks restored file existence, owner-only file modes, the private drill directory mode, restored row counts, and post-write hash verification.
If you pass `--drill-output-dir` under the repo, use `.teable-recovery-drill/`, `teable-recovery-drill/`, or `ea-teable-recovery-drill-*`; those paths are git-ignored.

For an explicit durable deployment profile, layer the prod override on top of the base compose:

```bash
bash scripts/deploy.sh
```

To expose the Gemini Vortex-backed Responses model aliases locally, layer the Gemini override onto the API service so the container can execute the host Gemini CLI with the host credential directory:

```bash
docker compose -f docker-compose.yml -f docker-compose.gemini.yml up -d --force-recreate ea-api
```

If a workflow needs both host tools and the host Gemini CLI, layer both overrides:

```bash
docker compose -f docker-compose.yml -f docker-compose.host-tools.yml -f docker-compose.gemini.yml up -d --force-recreate ea-api ea-worker ea-scheduler
```

Worker topology is explicit in [docker-compose.yml](docker-compose.yml):

- `ea-api`: HTTP API and inline queue drain for request-scoped work
- `ea-worker`: background queue drainer for general execution leases
- `ea-scheduler`: background queue drainer reserved for scheduled or dedicated lease ownership
- `ea-db`: Postgres runtime state

Standalone-compatible service aliases for shared operator scripts:

- `PROPERTYQUARRY_API_SERVICE`
- `PROPERTYQUARRY_WORKER_SERVICE`
- `PROPERTYQUARRY_SCHEDULER_SERVICE`
- `PROPERTYQUARRY_DB_SERVICE`

Then open `http://localhost:8090/health`.

## Runtime Docs

- EA design canon: [.codex-design/ea/START_HERE.md](.codex-design/ea/START_HERE.md)
- EA vision and surface system: [.codex-design/ea/VISION.md](.codex-design/ea/VISION.md), [.codex-design/ea/SURFACE_DESIGN_SYSTEM.md](.codex-design/ea/SURFACE_DESIGN_SYSTEM.md)
- EA first-value journey and copy rules: [.codex-design/ea/FIRST_VALUE_JOURNEY.md](.codex-design/ea/FIRST_VALUE_JOURNEY.md), [.codex-design/ea/COPY_PRINCIPLES.md](.codex-design/ea/COPY_PRINCIPLES.md)
- EA production-grade umbrella goal: [.codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md](.codex-design/ea/CONTINUOUS_IMPROVEMENT_GOAL.md)
- Working shorthand for that goal: make EA the user's dependable executive, conversation, and media operating system: proactive, cross-channel, self-healing, premium-quality, and governed by owning truth planes rather than assistant-local lore.
- Persistent execution lenses: `detect`, `decide`, `deliver`, `recover`, `prove`.
- Operator runbook: [RUNBOOK.md](RUNBOOK.md)
- Architecture map: [ARCHITECTURE_MAP.md](ARCHITECTURE_MAP.md)
- Product brief v2: [PRODUCT_BRIEF_V2.md](PRODUCT_BRIEF_V2.md)
- Product boundary: [PRODUCT_BOUNDARY.md](PRODUCT_BOUNDARY.md)
- HTTP examples: [HTTP_EXAMPLES.http](HTTP_EXAMPLES.http)
- Environment/profile guidance: [ENVIRONMENT_MATRIX.md](ENVIRONMENT_MATRIX.md)
- Release notes: [CHANGELOG.md](CHANGELOG.md)
- EA flagship truth plane: [EA_FLAGSHIP_TRUTH_PLANE.md](.codex-design/repo/EA_FLAGSHIP_TRUTH_PLANE.md)
- EA flagship gate seed: [EA_FLAGSHIP_RELEASE_GATE.json](.codex-design/repo/EA_FLAGSHIP_RELEASE_GATE.json)
- EA flagship release receipt: [EA_FLAGSHIP_RELEASE_GATE.generated.json](.codex-design/product/EA_FLAGSHIP_RELEASE_GATE.generated.json) (refresh with `python3 scripts/materialize_ea_flagship_release_gate.py`)
- EA weekly product pulse: [WEEKLY_PRODUCT_PULSE.generated.json](.codex-design/product/WEEKLY_PRODUCT_PULSE.generated.json) (refresh with `python3 scripts/materialize_weekly_product_pulse.py`)
- Milestone/state model: [MILESTONE.json](MILESTONE.json) (delivery history, not the flagship oracle)
- Skills catalog: [SKILLS.md](SKILLS.md)
- Workspace inventory and LTD notes: [LTDs.md](LTDs.md)
- BrowserAct content-template exporter: `python3 scripts/generate_browseract_content_templates.py` (includes 1min daily-bonus and billing/usage scaffold packets)
- Release preflight now keys off the EA flagship truth plane, gate seed, generated release receipt, and weekly pulse; `MILESTONE.json` remains supporting delivery history.
- The EA flagship gate also requires the EA product canon in `.codex-design/ea/*`, so product truth is not inferred from mirrored Chummer sources alone.
- Release preflight checklist includes the EA flagship truth-plane contract in `RELEASE_CHECKLIST.md`.
- `bash scripts/refresh_ltds_from_inventory.sh --input <inventory.json> --write` can rewrite the LTD discovery table from structured BrowserAct inventory output.
- `bash scripts/refresh_ltds_via_api.sh --binding-id <browseract-binding-id> --service-name BrowserAct --write` can execute the `ltd_inventory_refresh` skill and rewrite the LTD discovery table through the local API.
- `python3 scripts/verify_ltd_critical_entries.py` is the fail-closed check for the LTD lanes currently relied on in runtime (`1min.AI`, `Prompt Architects`, BrowserAct, and Teable). `scripts/hard_exit_gates.sh` now runs it before release smoke.
- `python3 scripts/verify_ltd_flagship_subset.py` is the broader flagship inventory gate. It does not claim the whole LTD catalog is verified; it enforces that the named flagship subset (`1min.AI`, `Prompt Architects`, `PayFunnels`, BrowserAct, Teable, ClickRank.ai, Emailit, Pixefy, Rafter) stays on accepted verification sources before release.
- `python3 scripts/verify_ltd_provider_lanes.py` materializes governed provider-lane receipts for the high-value LTD lanes, including source-of-truth boundaries, off-switches, allowed/forbidden inputs, and missing proof receipts.
- `python3 scripts/materialize_poppy_draft_packet.py --source-packet <packet.json> --draft-output <draft.txt>` records a Poppy draft-workbench receipt for public or operator-approved source packets. It keeps Poppy draft/operator only: runtime stays off, output remains pending human review, and EA/Chummer source material remains truth.
- `python3 scripts/materialize_memorial_voice_roundtrip_exit_gate.py --base-url http://127.0.0.1:8090` records the live memorial voice roundtrip receipt. It must pass before the whole-project map can clear the memorial voice/realtime blocker.
- `python3 scripts/materialize_memorial_phrase_bank.py` writes the approved Manfred memorial phrase bank with separate stable audio text and warmer visible fallback text.
- `python3 scripts/materialize_memorial_operator_status.py` writes `.codex-design/product/MEMORIAL_OPERATOR_STATUS.generated.json`, the operator-readable memorial status card showing local release-candidate state and whether the three public-origin gold receipts are still missing.
- `python3 scripts/materialize_memorial_room_audio_receipt_clean.py` records the manual room/device proof from a clean clone and copies the resulting receipt plus refreshed operator/gold artifacts back into the repo, so unrelated worktree drift does not poison the final room proof.
- `python3 scripts/materialize_whole_project_gold_map.py` writes `.codex-design/product/WHOLE_PROJECT_GOLD_MAP.generated.json`, the conservative map that keeps EA flagship readiness separate from owning-repo authority. A `gold` status means EA-controlled receipt-set gold only; it is not a blanket claim that EA owns Chummer, Fleet, Property, media-provider, or design truth.
- `python3 scripts/verify_whole_project_gold_map.py` fails closed if that map overclaims gold or promotes Poppy/media/memorial lanes beyond their governed receipt state.
- `python3 scripts/verify_memorial_voice_stability_gate.py` runs repeated deployed memorial voice loops. Use it before any public memorial demo claim; the single published receipt is necessary but not an endurance proof.
- `make verify-ltd-critical-entries` runs the critical runtime LTD verifier.
- `make verify-ltd-flagship-subset` runs the broader flagship verified-subset gate.
- `make verify-ltd-provider-lanes` runs the governed provider-lane verifier.
- `make ltd-release-gates` runs all LTD release verifiers together.
- Optional FastestVPN sidecar support is available in [docker-compose.fastestvpn.yml](docker-compose.fastestvpn.yml). Put FastestVPN `*.ovpn` files under [vpn/fastestvpn/README.md](vpn/fastestvpn/README.md), or fetch them with [bootstrap_fastestvpn_configs.sh](scripts/bootstrap_fastestvpn_configs.sh), then start `ea-fastestvpn-proxy` with the main EA services so BrowserAct login traffic goes out through a local rotating HTTP proxy. If you deploy through `scripts/deploy.sh`, keep the overlay explicit with `EA_ENABLE_FASTESTVPN=1`.
- The FastestVPN overlay also uses `ea-docker-socket-proxy` instead of a raw runtime socket mount, constrains that sidecar with dropped capabilities, `no-new-privileges`, read-only rootfs, and bounded memory/PID limits, mounts only `docker-compose.yml`, `docker-compose.fastestvpn.yml`, and `vpn/fastestvpn/` rather than the whole repository, and applies the same non-root, read-only-rootfs, dropped-capability, `no-new-privileges`, and bounded memory/PID operator constraints as the host-tools profile.

## Operator Shortcuts

- `make materialize-release-assets`: run the full release-truth bundle in order, including deploy context, release manifest, and release-authority status
- `make materialize-release-manifest`: regenerate `.codex-studio/published/release_manifest.generated.json` after refreshing deploy context
- `make verify-release-assets`: materialize and verify the EA flagship receipts, whole-project gold map, bounded design-mirror bundle, release-authority gate, and authoritative live runtime release posture
- `make verify-release-authority`: fail closed unless the release manifest records a runtime public origin, explicit deployment id, clean worktree, and compose topology strong enough for a shipping claim
- `make materialize-release-authority-status`: refresh deploy context, regenerate the release manifest, then write `.codex-studio/published/release_authority_status.generated.json`
- `make materialize-deploy-context`: write the deploy-context artifact consumed by release-manifest materialization; it records the authoritative release tuple for the deploy attempt: repository, branch, tracking branch, commit, deployment id, public origin, release label, project mode, and compose topology
- `make verify-deploy-context`: verify the deploy-context artifact before trusting release-manifest inputs
- `make verify-release-authority-runtime`: compare live `/version` and `/health/release-authority` responses against the published release-authority status artifact
- `make verify-release-authority-runtime-authoritative`: fail unless the runtime is internally consistent and the nested release/deploy gates both pass with `clear` / `authoritative_runtime`
- `make release-authority-probe`: fetch the live `/health/release-authority` payload from the local runtime and print the operator summary
- `make materialize-memorial-phrase-bank`: regenerate the approved Manfred memorial phrase bank artifact
- `make materialize-memorial-operator-status`: regenerate the operator-readable memorial local/public-gold status artifact
- `make materialize-memorial-room-audio-gold-clean`: record the manual room/device proof from a clean clone and copy the refreshed memorial gold artifacts back into the repo
- `make verify-design-mirror-bundle`: inspect only the bounded EA design-mirror bundle parity
- `make repair-design-mirror-bundle`: restore the bounded EA design-mirror bundle from canonical sources

## Runtime Spine

- `app.main` exposes a FastAPI app
- `/health`, `/health/live`, `/health/ready`, `/version`, and `/health/release-authority` provide liveness/readiness/version/release-authority probes
- `/version` now also exposes `release_authority_state`, `release_authority_posture`, and `release_authority_source` so operators can see whether the compact runtime probe is reading the published release-authority artifact or falling back to manifest recomputation.
- Codex provider compatibility façade:
  - `GET /v1/models`
  - `POST /v1/responses`
  - `GET /v1/responses/{response_id}`
  - `GET /v1/responses/{response_id}/input_items`
  - `GET /v1/responses/_provider_health`
  - `GET /v1/codex/profiles` for lane/provider health and account attribution
  - `POST /v1/providers/onemin/probe-all` for explicit per-slot 1min validation
  - `POST /v1/codex/core` (hard lane, forced `ea-coder-hard`)
  - `POST /v1/codex/easy` (fast lane, forced `ea-coder-fast`)
  - `POST /v1/codex/repair` (bounded-fix lane, prefers `ea-repair-gemini` and promotes to `ea-onemin-coder` when cheap repair backends are unavailable)
  - `POST /v1/codex/groundwork` (Gemini groundwork lane, forced `ea-groundwork-gemini`)
  - `POST /v1/codex/review-light` (cheap review lane, forced `ea-review-light`)
  - `POST /v1/codex/survival` (slow backup lane, forced `ea-coder-survival`, background/poll only in v1)
  - `POST /v1/codex/audit` (jury lane, forced `ea-audit-jury`)
  - stream mode via `Accept: text/event-stream`
  - survival mode is intentionally non-streaming in v1; create returns an `in_progress` response object and clients poll `GET /v1/responses/{response_id}` until completion
  - `GET /v1/models` returns the public EA aliases plus the currently configured upstream model IDs so Codex can target concrete provider backends when needed.
  - `EA_RESPONSES_PROVIDER_ORDER`, `EA_RESPONSES_CHEAP_PROVIDER_ORDER`, and `EA_RESPONSES_HARD_PROVIDER_ORDER` tune normal, fast/cheap, and hard lane provider order without patching the router; provider aliases such as `1min` and `magicx` normalize to the runtime keys.
  - `GET /v1/responses/_provider_health` and `GET /v1/codex/profiles` expose account-name attribution, owner-ledger metadata matched by hash or stable slot/account identifiers, latest explicit probe result, observed `remaining_credits` / `required_credits`, per-slot `observed_consumed_credits` / `observed_success_count`, aggregate `estimated_remaining_credits_total` / `remaining_percent_of_max`, rolling `estimated_burn_credits_per_hour` / `estimated_hours_remaining_at_current_pace`, and deleted-key quarantine state without returning raw API secrets.
  - `python3 scripts/sync_onemin_owner_ledger.py --write` refreshes `config/onemin_slot_owners.json` from the current `ONEMIN_AI_API_KEY*` values plus any `ONEMIN_DIRECT_API_KEYS_JSON(_FILE)` manifest entries while preserving the existing owner roster metadata by slot/account.
  - The template-backed 1min BrowserAct login lanes can now read a generic rotating proxy from `EA_UI_BROWSER_PROXY_SERVER`, `EA_UI_BROWSER_PROXY_USERNAME`, `EA_UI_BROWSER_PROXY_PASSWORD`, and `EA_UI_BROWSER_PROXY_BYPASS`, and `ONEMIN_BROWSERACT_MAX_ACCOUNTS_PER_REFRESH` / `EA_ONEMIN_BILLING_REFRESH_MIN_INTERVAL_SECONDS` control whether one refresh cycle can sweep the full configured slot set without the old per-minute cadence gate.
  - [rotate_fastestvpn_proxy.sh](scripts/rotate_fastestvpn_proxy.sh) recreates the FastestVPN sidecar plus EA services with `docker compose up -d --no-build --force-recreate --no-deps` so BrowserAct can pick up a fresh FastestVPN exit profile before a broad 1min sweep without rebuilding the EA runtime.
  - `GET /v1/models` includes the Gemini Vortex-backed `ea-gemini-flash` public alias, the groundwork aliases `ea-groundwork-gemini` and `ea-groundwork`, plus the concrete `gemini-3.5-flash` model id when that backend is configured.
  - the survival lane reduces the request locally first, then tries Gemini Vortex, then BrowserAct Gemini web, and only then a single-role ChatPlayground tie-break
  - UI-backed survival backends are challenge-aware: Cloudflare/Turnstile/human-verification or session-expiry responses put that backend on cooldown and survival falls through to the next backend instead of trying to automate the challenge

### Codex Configuration Example

```toml
model = "ea-coder-best"
model_provider = "ea"

[model_providers.ea]
name = "Executive Assistant"
base_url = "http://ea-host:8090/v1"
wire_api = "responses"
env_key = "EA_API_TOKEN"
env_http_headers = { "X-EA-Principal-ID" = "EA_PRINCIPAL_ID" }
stream_idle_timeout_ms = 300000
stream_max_retries = 5
```

For the explicit survival lane, point Codex at the dedicated alias instead of the default lane:

```toml
model = "ea-coder-survival"
model_provider = "ea"
```

If your Codex deployment prefers `x-api-token` for auth instead of bearer, add this style:

```toml
model = "ea-coder-best"
model_provider = "ea"

[model_providers.ea]
name = "Executive Assistant"
base_url = "http://ea-host:8090/v1"
wire_api = "responses"
env_key = "EA_API_TOKEN"
env_http_headers = { "x-api-token" = "EA_API_TOKEN", "X-EA-Principal-ID" = "EA_PRINCIPAL_ID" }
stream_idle_timeout_ms = 300000
stream_max_retries = 5
```

- `/v1/rewrite/artifact` creates an artifact and an execution session
- `/v1/rewrite/artifacts/{artifact_id}` fetches persisted artifact content directly from the durable artifact store, including explicit `principal_id` ownership plus the originating task key and deliverable type for non-rewrite runs alongside `mime_type`, `preview_text`, a stable `storage_handle`, durable `body_ref`, and structured attachment metadata
- `/v1/rewrite/receipts/{receipt_id}` and `/v1/rewrite/run-costs/{cost_id}` expose direct execution proof records without requiring full session expansion, including originating task identity for non-rewrite runs
- `/v1/rewrite/sessions/{session_id}` exposes execution ledger detail (events, steps, queue items, receipts, artifacts, costs, human task packets, and human task assignment history), now includes `intent_skill_key`; inline artifact/proof rows now carry originating task identity and resolved `skill_key` for non-rewrite runs
- rewrite and generic task execution artifact payloads now also project explicit `principal_id` ownership, `mime_type`, `preview_text`, a stable `storage_handle`, durable `body_ref`, and `structured_output_json` / `attachments_json`, so artifact reads can keep inline content while moving toward real metadata-plus-handle envelopes
- `/v1/rewrite/sessions/{session_id}` inline human-task assignment-history rows now carry originating task identity too, so one-fetch operator views keep non-rewrite task context in the embedded transition log
- `/v1/rewrite/sessions/{session_id}` inline human-task packet rows now carry originating task identity too, so paused non-rewrite packet detail stays self-describing inside the main session envelope
- `/v1/human/tasks*` manages principal-scoped human review/work packets linked back to execution sessions and steps
- `/v1/human/tasks/operators*` manages principal-scoped operator profiles with role, skill-tag, and trust-tier metadata used for specialized backlog routing
- `/v1/human/tasks/backlog` and `/v1/human/tasks/mine` expose direct operator backlog views on top of the human task queue
- `/v1/human/tasks/{human_task_id}/assign` allows pre-assigning operator ownership before the task is claimed into active work, and can consume a computed `auto_assign_operator_id` when the caller omits `operator_id`
- `/v1/human/tasks/{human_task_id}/assignment-history` exposes task-scoped ownership transitions, now carries originating task identity too, and supports filtering by transition name, assigned operator, or assigning actor without requiring callers to diff the full session event stream
- `/v1/human/tasks/unassigned` and `assignment_state=unassigned|assigned|claimed|returned` expose the difference between ownerless pending work, pre-assigned pending work, active claims, and returned packets
- human task payloads and session-linked `human_tasks` now project `routing_hints_json` with `suggested_operator_ids`, `recommended_operator_id`, and `auto_assign_operator_id` so specialized reviewers can be suggested or preselected without a separate profile-filtered backlog scan
- `/v1/observations/ingest` and `/v1/observations/recent` provide channel-agnostic observation intake
- `/v1/delivery/outbox` endpoints provide channel-agnostic queued delivery tracking
- `/v1/delivery/outbox/{delivery_id}/failed` marks retry/dead-letter transitions with error context
- `/v1/tools/registry*` manages typed tool contracts (`tool_name`, schemas, policy metadata)
- `/v1/tools/execute` runs built-in tool handlers through the shared execution plane, including `browseract.extract_account_facts` and `browseract.extract_account_inventory` for BrowserAct-backed LTD discovery plus `connector.dispatch` for queued sends
- `/v1/connectors/bindings*` manages external connector bindings and status transitions
- `/v1/providers/bindings*` manages persisted principal-scoped provider bindings, status transitions, and probe evidence updates
- `/v1/providers/states*` projects effective provider routing posture (catalog defaults + persisted binding/probe health state)
- `/v1/tasks/contracts*` manages typed task contracts used by intent compilation
- `/v1/skills*` promotes those task contracts into product-facing executive skills with explicit workflow, memory, authority, provider-hint, human-policy, and evaluation metadata, including guide-copy and visual-direction lanes backed by Gemini Vortex, the BrowserAct-backed `browseract_bootstrap_manager` lane for on-demand workflow-spec generation across prompt-tool and page-extract templates, and the Gemini-assisted `browseract_workflow_repair_manager` lane for self-healing broken BrowserAct specs
- `/v1/plans/compile` emits a typed plan DSL projection from task contracts, projects the resolved `skill_key`, and now accepts either `task_key` or `skill_key` as the entrypoint selector
- `/v1/plans/execute` runs task-contract keys through the same queue-backed graph runtime used by rewrite execution, returns the resolved `skill_key` alongside `task_key`, and now accepts either `task_key` or `skill_key`
- direct rewrite/session artifact, receipt, and run-cost projections now carry the resolved `skill_key` too, so the main runtime inspection surfaces stay product-facing once a task contract is promoted into a first-class skill
- the runtime now also keeps typed read projections for task-contract policy (`TaskContractPolicyRecord`), product-facing skills (`SkillCatalogRecord`), and provider posture (`ProviderBindingState`) so planner/catalog/provider code reads structured records instead of re-parsing raw JSON blobs at every call site
- `/v1/evidence/objects*` exposes principal-scoped evidence-pack projections with stable `citation_handle` values and filters for `artifact_id`, `session_id`, or `evidence_ref`
- `/v1/evidence/merge` combines selected evidence rows back into a reusable evidence pack so downstream workflows can merge cited facts without reparsing artifact JSON
- `/v1/memory/candidates*` stages reviewable memory candidates from runtime signals
- `/v1/memory/items*` lists promoted long-term memory items with provenance
- `/v1/memory/entities*` upserts/list/gets semantic entities for people/projects/objects
- `/v1/memory/relationships*` upserts/list/gets relationship edges between entities
- `/v1/memory/commitments*` upserts/list/gets principal-scoped commitments
- `/v1/memory/authority-bindings*` upserts/list/gets principal-scoped authority bindings
- `/v1/memory/delivery-preferences*` upserts/list/gets principal-scoped delivery preferences
- `/v1/memory/follow-ups*` upserts/list/gets principal-scoped follow-up records
- `/v1/memory/deadline-windows*` upserts/list/gets principal-scoped deadline windows
- `/v1/memory/stakeholders*` upserts/list/gets principal-scoped stakeholder profiles
- `/v1/memory/decision-windows*` upserts/list/gets principal-scoped decision windows
- `/v1/memory/communication-policies*` upserts/list/gets principal-scoped communication policies
- `/v1/memory/follow-up-rules*` upserts/list/gets principal-scoped follow-up automation rules
- `/v1/memory/interruption-budgets*` upserts/list/gets principal-scoped interruption budgets
- `/v1/memory/context-pack` synthesizes task-ready context packs (memory items, promotion signals, conflict detection, commitment risks, unresolved refs) for a principal-scoped goal
- the principal-scoped memory seed surface is explicitly covered by both `tests/smoke_runtime_api.py` and the approved host smoke path (`scripts/smoke_api.sh` via `scripts/smoke_postgres.sh`)
- principal-scoped rewrite/session/artifact/receipt/run-cost, plan-compile/execute, connector, human-task, and memory routes now derive their effective principal from `X-EA-Principal-ID` or `EA_DEFAULT_PRINCIPAL_ID` instead of trusting caller-supplied body/query IDs
- caller-supplied `principal_id` on those rewrite and plan routes is now a compatibility field only; mismatches fail with `403 principal_scope_mismatch`, and foreign-principal session/artifact/receipt/run-cost fetches are blocked the same way
- session-bound human task create/list requests now also enforce the linked execution session principal, so one principal cannot attach packets to or enumerate another principal's execution thread by reusing its `session_id`
- rewrite execution now records `plan_compiled`, runs a typed three-step queue path (`step_input_prepare` -> `step_policy_evaluate` -> `step_artifact_save`) through the execution ledger, and dispatches tool steps through a registry-backed `ToolExecutionService`
- `policy_decision` is now recorded by the queued `step_policy_evaluate` handler after `input_prepared`, so approval/block ledger records reflect actual runtime step order instead of preflight-only bookkeeping
- `POST /v1/plans/compile` now exposes explicit plan-step dependencies plus declared input/output keys, and queue advancement now enqueues every currently ready step from satisfied dependency edges instead of parent-linked step order while paused sessions stop further leasing
- planner and orchestrator startup now validates duplicate step keys, unknown dependency keys, and dependency cycles before queue execution starts, so invalid plan graphs fail before any runtime rows or leases are created
- queued step execution now only merges declared dependency inputs and validates declared step outputs before completion, so `input_keys` / `output_keys` drift fails fast instead of leaking undeclared payloads across the graph
- session-step `parent_step_id` now mirrors only real single-dependency edges; multi-prerequisite join steps stay parentless and rely on `dependency_keys` plus `dependency_states` for graph truth
- compiled plan steps now also project explicit `owner`, `authority_class`, `review_class`, `failure_strategy`, `timeout_budget_seconds`, `max_attempts`, and `retry_backoff_seconds` semantics so executive workflows expose who owns each step and what runtime posture it expects before the DAG grows deeper
- queued step failures now honor `failure_strategy=retry` plus `max_attempts` and `retry_backoff_seconds`, rescheduling the same queue row for another lease instead of immediately terminally failing the whole session on the first transient tool error
- zero-backoff retries now keep draining same-session queue work inline through create/approve/return flows, so transient first-attempt tool failures do not bubble as `queued task did not execute` when the retry row is already immediately eligible
- nonzero-backoff retries now surface as a first-class `202 queued` async acceptance on rewrite and plan execution instead of collapsing into `queued task did not execute`, so future-scheduled retry rows can be polled through the same workflow contract as approval and human-review pauses
- the execution ledger now uses an explicit `set_session_status(...)` transition API for `queued`, `running`, `blocked`, `awaiting_approval`, `awaiting_human`, and `failed` states, so retries and pause/resume flows no longer masquerade as “session completion” in the runtime code path
- task contracts can now also compile non-default retry posture into built-in workflow steps with `budget_policy_json.artifact_failure_strategy|artifact_max_attempts|artifact_retry_backoff_seconds` and `dispatch_failure_strategy|dispatch_max_attempts|dispatch_retry_backoff_seconds`
- task contracts and skill surfaces now normalize that same `budget_policy_json` payload into typed runtime policy models (`artifact_retry`, `dispatch_retry`, `human_review`, `memory_candidate`, `artifact_output`, and `skill_catalog`), so planner/runtime code consumes one canonical contract instead of re-reading ad-hoc policy keys at every boundary
- `POST /v1/plans/execute` now reuses that same compiled task-contract runtime for non-`rewrite_text` artifact flows, accepts structured `input_json` plus `context_refs` in addition to the legacy `text` convenience field, injects synthesized `context_pack` payloads from principal-scoped memory reasoning, and lets executive contracts like stakeholder briefings run through the queue-backed graph without hardcoding the rewrite vertical
- `POST /v1/plans/execute` also returns the same first-class `202 awaiting_approval` and `202 awaiting_human` async contract as rewrite execution, and those generic task sessions resume through the shared approval and human-task endpoints
- Those paused non-rewrite sessions keep the same dependency-state projection in `GET /v1/rewrite/sessions/{session_id}` too: approval-backed runs show `step_artifact_save.state=waiting_approval` with satisfied dependencies, while human-review-backed runs keep downstream save steps queued behind `blocked_dependency_keys=["step_human_review"]` until the packet returns
- Task contracts can now project a first-class `human_task` branch (`step_human_review`) in plan output by setting `budget_policy_json.human_review_role`, `human_review_priority`, `human_review_sla_minutes`, `human_review_auto_assign_if_unique`, `human_review_desired_output_json`, `human_review_authority_required`, `human_review_why_human`, and `human_review_quality_rubric_json`; rewrite execution now returns `202 awaiting_human` when that compiled review step pauses the queue runtime, creates the linked human task with those routing and review-contract semantics, can auto-preassign a unique exact reviewer when the policy flag is enabled, and downstream artifact persistence can consume `returned_payload_json.final_text` from the completed review packet
- Task contracts can now also choose a materially different workflow skeleton with `budget_policy_json.workflow_template`; the built-in `artifact_then_dispatch` template compiles `step_input_prepare -> step_artifact_save -> step_policy_evaluate -> step_connector_dispatch`, persists the artifact before approval, then resumes into `connector.dispatch` only after the approval-backed delivery gate is cleared
- Task contracts can now also use the generic `workflow_template=tool_then_artifact` macro plus `budget_policy_json.pre_artifact_tool_name=<tool>` to compile a reusable pre-artifact tool branch, and the supported BrowserAct slices now prove both `browseract.extract_account_facts` and `browseract.extract_account_inventory` can run through `step_input_prepare -> ... -> step_artifact_save` without needing one-off planner paths
- Task contracts can now also choose `workflow_template=browseract_extract_then_artifact`, compiling `step_input_prepare -> step_browseract_extract -> step_artifact_save` so BrowserAct-backed account discovery can extract tier/email/status facts and persist them as a structured artifact in one queue-backed flow
- `/v1/skills` now projects a first-class skill catalog layer over task contracts, so executive capabilities like `meeting_prep`, `ltd_inventory_refresh`, the BrowserAct-backed `browseract_bootstrap_manager`, the repair-focused `browseract_workflow_repair_manager`, the design-governance lanes `design_petition`, `design_synthesis`, and `mirror_status_brief`, plus the Gemini-backed guide-copy and visual-direction lanes, can persist product-facing metadata (`memory_reads`, `memory_writes`, authority/tool/human/provider policy, evaluation cases, and workflow template selection) without introducing a second storage system; `design_petition` and `design_synthesis` turn blocked-by-design escalation and repeated finding clustering into explicit runtime work, the guide-copy lane records reviewed public-copy facts, the visual-direction lane records reviewed style-epoch plus scene-ledger facts so art direction can remember what it already rendered, `SKILLS.md` tracks the current catalog, and `GET /v1/skills?provider_hint=BrowserAct` filters the catalog by LTD-backed provider hints
- Guide-generation text now routes through EA + Gemini Vortex only. If that lane is unavailable, the worker fails instead of quietly falling back to Codex.
- That same skill layer is now callable directly through the generic plan runtime too: `POST /v1/plans/compile` and `POST /v1/plans/execute` accept `skill_key` as a first-class selector, so product-facing clients do not have to reverse-map back to `task_key` before compiling or running a skill.
- Task contracts can now also use `workflow_template=artifact_then_packs` plus `budget_policy_json.post_artifact_packs=[...]` to compose shared post-artifact planner branches without minting a new one-off named workflow template for every dispatch/memory combination
- The built-in `artifact_then_memory_candidate` workflow template now compiles `step_input_prepare -> step_policy_evaluate -> step_artifact_save -> step_memory_candidate_stage`, persists the artifact, then stages a pending principal-scoped memory candidate through the queue runtime so task contracts can emit reviewable memory without a second API-side post-process
- Task contracts can now also set `budget_policy_json.artifact_output_template=evidence_pack`, causing `step_input_prepare` to emit structured `claims`, `evidence_refs`, `open_questions`, and `confidence` metadata that flows into `step_artifact_save`, persists as a first-class evidence envelope, and carries forward into downstream memory-candidate staging instead of being trapped in freeform text
- Those `evidence_pack` artifact saves now also materialize first-class evidence rows behind `/v1/evidence/objects`, project stable `evidence_object_id` / `citation_handle` metadata through the artifact-save step output, and let `/v1/evidence/merge` recombine cited rows without reparsing the original artifact body
- The built-in `artifact_then_dispatch_then_memory_candidate` workflow template now compiles `step_input_prepare -> step_artifact_save -> step_policy_evaluate -> step_connector_dispatch -> step_memory_candidate_stage`, so an approval-backed external action can complete first and then stage a pending memory candidate with delivery context from the finished workflow
- That same `artifact_then_dispatch_then_memory_candidate` template can also combine with `budget_policy_json.human_review_role`, compiling `step_input_prepare -> step_human_review -> step_artifact_save -> step_policy_evaluate -> step_connector_dispatch -> step_memory_candidate_stage` so sensitive send workflows can pause for human judgment first and still stage post-dispatch memory only after approval-backed delivery completes
- That same `artifact_then_dispatch` template can also combine with `budget_policy_json.human_review_role`, compiling `step_input_prepare -> step_human_review -> step_artifact_save -> step_policy_evaluate -> step_connector_dispatch` so sensitive send flows can pause for human review before artifact persistence and still pause again for approval before dispatch
- That review-then-dispatch branch now also preserves compiled `dispatch_failure_strategy|max_attempts|retry_backoff_seconds` metadata end to end, so approval-resumed `connector.dispatch` retries can legitimately leave the session `queued` behind a future `next_attempt_at` instead of erroring after human review clears, and the HTTP smoke suite now proves that queued post-approval send path too
- Unknown `budget_policy_json.workflow_template` values now fail fast during plan compilation and task execution with `422 unknown_workflow_template:<value>` instead of silently falling back to the rewrite skeleton
- compiled human-review steps now merge dependency outputs into the created packet input too, so `normalized_text`, `text_length`, and reviewer overrides flow into human-task context without relying on parent-step-only ordering
- rewrite tool receipts now carry a normalized `tool.v1` invocation contract for the built-in `artifact_repository` handler, and the runtime self-heals missing built-in tool definitions before execution if the registry starts empty
- the built-in `connector.dispatch` handler now also runs through `ToolExecutionService`, self-heals its built-in registry definition the same way, and queues durable delivery outbox rows
- `connector.dispatch` now requires an enabled connector binding that matches the request principal before `/v1/tools/execute` can queue delivery
- the built-in `browseract.extract_account_facts` and `browseract.extract_account_inventory` handlers now also run through `ToolExecutionService`, resolve BrowserAct-backed single-service or multi-service account facts from a scoped connector binding, accept optional live `run_url` plus `instructions` / `account_hints_json` for BrowserAct-driven verification, and can feed those facts straight into structured artifact persistence with the live-hint provenance kept in the output envelope
- observation intake supports `source_id`/`external_id`/`dedupe_key` attribution and auth/raw-payload pointers
- delivery outbox supports idempotency keys plus retry/dead-letter state fields
- `/v1/channels/telegram/ingest` maps raw Telegram updates into normalized observation events
- `/v1/policy/decisions/recent` exposes persisted policy decision audit records scoped to the effective request principal
- `/v1/policy/evaluate` exposes direct policy checks for tool/action/channel plus step/authority/review metadata, including external-send approval branches, and treats body `principal_id` as a compatibility field that must match the request principal
- `/v1/policy/approvals/*` exposes pending/history plus approve/deny/expire decision endpoints scoped to the effective request principal, and those approval projections now carry the originating task identity for non-rewrite async work
- `/v1/human/tasks*` queue/detail payloads now also carry the originating task identity, so paused non-rewrite async work stays self-describing before completion
- human task packets append `human_task_created`, `human_task_claimed`, and `human_task_returned` events into the linked session ledger so returned-from-human work is auditable
- human task packets can optionally reopen a linked step into `waiting_human`, move the session to `awaiting_human`, and resume that step to completion when the operator returns the packet
- human task queue listings now support operator-facing `role_required`, `assigned_operator_id`, and `overdue_only` filters for targeted reviewer backlogs
- human task payloads now include explicit `assignment_state` values (`unassigned`, `assigned`, `claimed`, `returned`) so pre-assigned pending work is first-class in session and queue projections
- human task payloads now also persist `assignment_source` so manual assignment, route-level recommended assignment, and planner auto-preselection remain distinguishable in session/operator views after later claim and return transitions
- human task payloads now also persist `assigned_at` and `assigned_by_actor_id` so current reviewer ownership includes timestamped actor provenance across manual assignment, claim, and planner auto-preselection paths
- human task list/detail/session rows now also expose compact `last_transition_event_name`, `last_transition_at`, `last_transition_assignment_state`, `last_transition_operator_id`, `last_transition_assignment_source`, and `last_transition_by_actor_id` fields so operators can see the latest ownership change without fetching the full assignment-history chain
- `GET /v1/human/tasks*` and `GET /v1/human/tasks/backlog` now also accept `sort=created_asc` for oldest-created FIFO triage, `sort=priority_desc_created_asc` so urgent and high packets float first while each priority band stays oldest-created-first, `sort=last_transition_desc` for freshest ownership churn, `sort=sla_due_at_asc` for earliest pending SLA, and `sort=sla_due_at_asc_last_transition_desc` to break same-SLA ties by the freshest ownership churn instead of repository/default order
- human task queue views now also accept `priority=<level>` filters so list, backlog, unassigned, and mine views can isolate `urgent`, `high`, `normal`, or `low` work before sorting, and comma-separated values like `priority=urgent,high` pull multiple priority bands in one request
- human task queue views now also accept `assignment_source=<source>` so list, backlog, and mine queues can open the same manual, recommended, or planner `auto_preselected` pending slices exposed by the priority summary endpoint
- Manual and planner auto-preselected `priority-summary?assignment_source=...` slices are now also rechecked after extra ownerless rows are added, so mixed-source churn does not contaminate non-ownerless summary counts.
- `GET /v1/human/tasks/unassigned?assignment_source=none` now isolates ownerless pending packets without requiring clients to filter for empty-string ownership sources after fetch
- `GET /v1/human/tasks/backlog?assignment_state=unassigned&assignment_source=none` now matches that same ownerless alias contract in the direct backlog view, so operator queues and unassigned-only views stay aligned
- `GET /v1/human/tasks/backlog?assignment_state=unassigned&assignment_source=none&sort=created_asc` now has explicit FIFO smoke coverage, so oldest-first ownerless backlog slices stay predictable for operator triage
- `GET /v1/human/tasks/backlog?assignment_state=unassigned&assignment_source=none&sort=last_transition_desc` now has explicit untouched-ownerless coverage too, so newest ownerless packets surface first when triage switches to freshest-ownership ordering
- `GET /v1/human/tasks/unassigned?assignment_source=none&sort=created_asc` now mirrors that FIFO behavior on the direct unassigned queue, keeping oldest-first ownerless triage aligned with the backlog slice
- `GET /v1/human/tasks/unassigned?assignment_source=none&sort=last_transition_desc` now mirrors that newest-first ordering on the dedicated unassigned queue, keeping backlog and unassigned-only triage aligned
- `GET /v1/human/tasks?status=pending&assignment_state=unassigned&assignment_source=none&sort=created_asc` now mirrors the same FIFO ownerless ordering on the general pending list, so list, backlog, and unassigned triage stay aligned
- `GET /v1/human/tasks?status=pending&assignment_state=unassigned&assignment_source=none&sort=last_transition_desc` now has matching newest-first untouched-ownerless coverage, so every pending queue surface shares the same freshest-transition contract
- Those ownerless backlog, unassigned, and general pending `assignment_source=none` sorted queue slices are now also explicitly covered alongside manual and auto-preselected neighbors, so both `sort=created_asc` and `sort=last_transition_desc` keep non-ownerless rows out under mixed-source churn
- `GET /v1/human/tasks?session_id=<id>&assignment_source=none&sort=created_asc` now gives the session-scoped ownerless slice the same FIFO contract, so session-local triage can stay aligned with list, backlog, and unassigned queues
- `GET /v1/human/tasks?session_id=<id>&assignment_source=none&sort=last_transition_desc` now gives the session-scoped ownerless slice the same newest-first untouched-ownerless contract, so per-session triage stays aligned with the global queue views
- Those same session-scoped `assignment_source=none` sorted queue slices are now explicitly covered alongside manual and auto-preselected neighbors too, so both `sort=created_asc` and `sort=last_transition_desc` keep non-ownerless rows out under mixed-source churn
- `GET /v1/rewrite/sessions/{session_id}?human_task_assignment_source=none` now has explicit multi-task ownerless projection coverage too, so the filtered `human_tasks` array and inline `human_task_assignment_history` both stay oldest-first for stable session-local audit views
- That same `human_task_assignment_source=none` session-detail slice is now explicitly covered alongside manual and auto-preselected work too, so current `human_tasks` stay ownerless-only while inline empty-source creation history remains oldest-first under mixed-source churn
- That same mixed-source session-detail ownerless slice is now also explicitly count-checked, so the current `human_tasks` block stays at two ownerless rows while inline empty-source history still exposes a longer audit trail under mixed-source churn
- `GET /v1/human/tasks?session_id=<id>&assignment_source=<source>` now also opens those same ownership-source slices inside one session, so session-local manual or planner-preselected review queues do not require client-side filtering
- `GET /v1/human/tasks/priority-summary` now exposes queue counts by priority band so operators can decide whether to pull `urgent`, `urgent,high`, or the full backlog before opening a reviewer queue
- `GET /v1/human/tasks/priority-summary` also accepts `assigned_operator_id` so assigned reviewer queues can expose their own priority-band load instead of only the global pending backlog
- `GET /v1/human/tasks/priority-summary` also accepts `operator_id` so pre-claim reviewer routing can count only the pending packets that exactly match an operator profile’s role, rubric-derived skill tags, and trust tier before that reviewer opens the backlog
- `GET /v1/human/tasks/priority-summary` also accepts `assignment_source`, and `assignment_state=unassigned&assignment_source=none` can count just ownerless pending packets without special empty-string handling
- That same ownerless `priority-summary?assignment_state=unassigned&assignment_source=none` slice is now explicitly covered after mixed-source churn too, so totals and low-priority counts stay ownerless-only even while manual and auto-preselected work coexists
- The unsorted ownerless `assignment_source=none` list, backlog, and unassigned slices are now also explicitly covered after mixed-source churn, so multi-row queue fetches still contain only ownerless packets even while manual and auto-preselected work coexists
- The unsorted session-scoped `session_id=<id>&assignment_source=none` slice is now also explicitly covered after mixed-source churn, so multi-row per-session queue fetches still contain only ownerless packets even while manual and auto-preselected work coexists
- Both SLA-oriented sort modes now fall back to oldest-created ordering for tasks without `sla_due_at`, so unscheduled backlog stays stable even when newer packets are reassigned.
- `GET /v1/human/tasks/{human_task_id}/assignment-history` now filters the linked execution ledger down to ownership transitions so recommended assignment, later manual reassignment, claim, and return provenance remain queryable after the packet state has advanced
- `GET /v1/human/tasks/{human_task_id}/assignment-history` also accepts `event_name`, `assigned_operator_id`, `assigned_by_actor_id`, and `assignment_source` so operator tooling can isolate just recommended, manual, planner-preselected, or ownerless creation transitions without scanning the whole chain
- `/v1/rewrite/sessions/{session_id}` now also projects `human_task_assignment_history`, so operator UIs can render the same ownership transition chain inline with session events, steps, and linked human task packets without making a second history fetch
- `/v1/rewrite/sessions/{session_id}` also accepts `human_task_assignment_source`, including `human_task_assignment_source=none` for current ownerless packets plus empty-source creation history, so session detail can surface one ownership slice without client-side filtering
- human task payloads now also compute reviewer routing hints from active operator profiles, rubric-derived skill tags, and trust-tier requirements so the best reviewer candidate can be surfaced directly on each packet
- approving a paused rewrite now resumes execution inline and completes the artifact/ledger flow instead of stopping at a dead intermediate status
- approval-required rewrite requests now return `202 Accepted` with `session_id`, `approval_id`, and `status=awaiting_approval` instead of an error-shaped denial
- rewrite execution now persists durable `execution_queue` rows and drains them inline for API requests before returning
- `app.runner` supports role-based startup (`EA_ROLE=api` or queue-draining worker roles)
- `app.domain.IntentSpecV3` and execution session/event models provide a typed kernel scaffold
- rewrite execution is gated by a centralized policy decision service (`policy_decision` event)

## Hardening Baseline

- app images no longer install `docker.io`
- runtime data/secrets are excluded from version control via a narrowed `.gitignore`

## Storage Backends

- `EA_RUNTIME_MODE=dev|test|prod` controls whether automatic memory fallback is allowed; `prod` fails fast instead
- `EA_STORAGE_BACKEND=postgres` forces Postgres-backed repositories (`DATABASE_URL` required)
- `EA_STORAGE_BACKEND=memory` keeps repositories in-process (dev/test convenience)
- `EA_STORAGE_BACKEND=auto` (default) attempts Postgres first, then falls back to memory in `dev`/`test`
- `EA_LEDGER_BACKEND` is still accepted as a temporary backward-compatible alias, but it is deprecated in favor of `EA_STORAGE_BACKEND`
- `EA_RUNTIME_MODE=prod` requires durable Postgres boot and rejects `memory` or `auto` degradation paths
- baseline schema migration: `ea/schema/20260305_v0_2_execution_ledger_kernel.sql`
- channel runtime migration: `ea/schema/20260305_v0_3_channel_runtime_kernel.sql`
- policy audit migration: `ea/schema/20260305_v0_4_policy_decisions_kernel.sql`
- artifact durability migration: `ea/schema/20260305_v0_5_artifacts_kernel.sql`
- execution-ledger v2 migration: `ea/schema/20260305_v0_6_execution_ledger_v2.sql`
- approvals workflow migration: `ea/schema/20260305_v0_7_approvals_kernel.sql`
- channel runtime reliability migration: `ea/schema/20260305_v0_8_channel_runtime_reliability.sql`
- tool/connector kernel migration: `ea/schema/20260305_v0_9_tool_connector_kernel.sql`
- task-contract kernel migration: `ea/schema/20260305_v0_10_task_contracts_kernel.sql`
- memory kernel migration: `ea/schema/20260305_v0_11_memory_kernel.sql`
- entities/relationships kernel migration: `ea/schema/20260305_v0_12_entities_relationships_kernel.sql`
- commitments kernel migration: `ea/schema/20260305_v0_13_commitments_kernel.sql`
- authority bindings kernel migration: `ea/schema/20260305_v0_14_authority_bindings_kernel.sql`
- delivery preferences kernel migration: `ea/schema/20260305_v0_15_delivery_preferences_kernel.sql`
- follow-ups kernel migration: `ea/schema/20260305_v0_16_follow_ups_kernel.sql`
- deadline windows kernel migration: `ea/schema/20260305_v0_17_deadline_windows_kernel.sql`
- stakeholders kernel migration: `ea/schema/20260305_v0_18_stakeholders_kernel.sql`
- decision windows kernel migration: `ea/schema/20260305_v0_19_decision_windows_kernel.sql`
- communication policies kernel migration: `ea/schema/20260305_v0_20_communication_policies_kernel.sql`
- follow-up rules kernel migration: `ea/schema/20260305_v0_21_follow_up_rules_kernel.sql`
- interruption budgets kernel migration: `ea/schema/20260305_v0_22_interruption_budgets_kernel.sql`
- execution queue kernel migration: `ea/schema/20260305_v0_23_execution_queue_kernel.sql`
- human tasks kernel migration: `ea/schema/20260305_v0_24_human_tasks_kernel.sql`
- human task resume kernel migration: `ea/schema/20260305_v0_25_human_task_resume_kernel.sql`
- human task assignment-state kernel migration: `ea/schema/20260305_v0_26_human_task_assignment_state.sql`
- human task review-contract kernel migration: `ea/schema/20260305_v0_27_human_task_review_contract.sql`
- operator profiles kernel migration: `ea/schema/20260305_v0_28_operator_profiles_kernel.sql`
- human task assignment-source kernel migration: `ea/schema/20260305_v0_29_human_task_assignment_source.sql`
- human task assignment provenance kernel migration: `ea/schema/20260305_v0_30_human_task_assignment_provenance.sql`

## Auth

- Set `EA_API_TOKEN=<token>` to require bearer auth on all non-health routes.
- Set `EA_DEFAULT_PRINCIPAL_ID=<principal>` to define the fallback request principal when `X-EA-Principal-ID` is omitted (default `principal-default`).
- Principal-scoped rewrite/session/artifact/receipt/run-cost, plan-compile, connector, human-task, and memory routes treat body/query `principal_id` as compatibility input only; mismatches against the request principal fail with `403 principal_scope_mismatch`.

## Policy Tuning

- `EA_APPROVAL_THRESHOLD_CHARS` sets rewrite input length requiring approval (default `5000`).
- `EA_APPROVAL_TTL_MINUTES` sets default approval request expiration window (default `120`).
- Policy decisions also consider declared tool/action metadata plus task risk and budget classes; disallowed tools fail closed with `policy_denied:tool_not_allowed`.
- `POST /v1/policy/evaluate` can dry-run external-send approval checks over HTTP without going through rewrite artifact creation, and now echoes the evaluated `step_kind`, `authority_class`, and `review_class` contract.
- `POST /v1/human/tasks` accepts `resume_session_on_return=true` to pause a linked step for human review and resume it when `/v1/human/tasks/{human_task_id}/return` is called.

## Operator Shortcuts

- Bootstrap during deploy: `EA_BOOTSTRAP_DB=1 bash scripts/deploy.sh`
- Memory-only local profile: `cp .env.local.example .env && EA_MEMORY_ONLY=1 bash scripts/deploy.sh`
- Common targets: `make deploy-ea-prod`, `make deploy-property`, `make env-backup-teable`, `make env-bootstrap-teable`, `make env-check-teable`, `make env-disable-extra-teable`, `make env-drill-teable`, `make env-ensure-local-teable`, `make env-local-status-teable`, `make env-probe-teable`, `make env-recover-teable`, `make verify-env-teable-recovery`, `make env-restore-teable`, `make env-restore-teable-local`, `make env-restore-teable-service`, `make bootstrap`, `make db-status`, `make db-size`, `make db-retention`, `make proactive-ooda`, `make verify-proactive-ooda`, `make operator-summary`, `make smoke-api`, `make smoke-api-principal`, `make smoke-postgres`, `make smoke-postgres-legacy`, `make release-smoke`, `make ci-gates-postgres`, `make ci-gates-postgres-legacy`, `make runtime-hard-exit-gates`, `make hard-exit-gates`, `make ltd-release-gates`, `make verify-ltd-critical-entries`, `make verify-ltd-flagship-subset`, `make all-local`, `make verify-release-assets`, `make release-docs`, `make release-preflight`
- OpenAPI export/diff: `scripts/export_openapi.sh`, `scripts/diff_openapi.sh`, `make openapi-export`, `make openapi-diff`
- Release checklist: `RELEASE_CHECKLIST.md`

## Proactive OODA Ink

EA can ingest every configured source it can reach in one pass: static signal files, generic discovery feeds, local opportunity rules, recent EA observations, and Google workspace signals. Each source is isolated, so a broken connector becomes a source-health OODA item instead of silencing the whole loop. EA then orients the combined signals into concise OODA ink and notifies the principal only when the result is actionable. The notification includes why it matters, the recommended decision/action, approval status, a staged action plan when available, the staged next-step contract, the external-action guardrail, the ignored consequence, and source evidence. Real non-dry runs also persist private stage packets next to the OODA state file by default so operator tooling can inspect reversible next steps after the notification. Persisted run receipts keep privacy-safe stage telemetry such as safe stage kind, artifact count, approval-gate hash, policy hash, and stage-packet hashes, but not the private staged packet text or links.

Run it manually or from cron:

```bash
make proactive-ooda
```

`make deploy-ea-prod` also starts `ea-proactive-ooda`, a lightweight Python service that runs the same OODA loop on `EA_PROACTIVE_OODA_INTERVAL_SECONDS`. It stays quiet unless `EA_PROACTIVE_OODA_ENABLED=1`.

Check readiness without sending a Telegram message:

```bash
make verify-proactive-ooda
```

Check the privacy-safe live Telegram delivery proof:

```bash
make verify-proactive-ooda-live-receipt
```

Useful runtime knobs:

- `EA_PROACTIVE_OODA_PRINCIPAL_ID`: principal to notify, default `principal-default`
- `EA_PROACTIVE_OODA_EMAIL_LIMIT` / `EA_PROACTIVE_OODA_CALENDAR_LIMIT`: workspace scan bounds when the full Google adapter is available
- `EA_PROACTIVE_OODA_GMAIL_QUERY`: optional Gmail query filter
- `EA_PROACTIVE_OODA_MAX_ITEMS`: maximum actionable items per run
- `EA_PROACTIVE_OODA_STATE_PATH`: dedupe state file, default `state/proactive_ooda_notified.json`
- `EA_PROACTIVE_OODA_CONTAINER_STATE_PATH`: container dedupe state path, default `/data/provider-ledger/proactive_ooda_notified.json`
- `EA_PROACTIVE_OODA_STAGE_PACKETS_ENABLED`: persist private staged next-step packet files for real runs, default `1`
- `EA_PROACTIVE_OODA_STAGE_PACKET_DIR`: override private stage-packet output directory; default is `proactive_ooda_stage_packets` next to the dedupe state file
- `EA_PROACTIVE_OODA_OBSERVATION_LOOKBACK_HOURS` / `EA_PROACTIVE_OODA_OBSERVATION_LIMIT`: fallback scan window for recent EA observation events
- `EA_PROACTIVE_OODA_PERSIST_RECEIPTS`: persist redacted run receipts into `observation_events`, default `1`
- `EA_PROACTIVE_OODA_SIGNALS_JSON`: optional file-backed signal feed
- `EA_PROACTIVE_OODA_DISCOVERY_JSON`: JSON source list for generic `json`, `jsonl`, `rss`, or `teable` discovery feeds
- `EA_PROACTIVE_OODA_OPPORTUNITY_RULES_JSON`: JSON opportunity rules for generic paid-assistant OODA loops; rules may use `always` or weather threshold triggers and can include `action_plan`, `stage`, and an external-action guardrail
- `EA_PROACTIVE_OODA_PAUSED` / `EA_PROACTIVE_OODA_PAUSE_REASON`: operator pause switch; actionable packets are still built and receipted as deferred, but delivery is skipped and refs stay unnotified
- `EA_PROACTIVE_OODA_QUIET_HOURS_START` / `EA_PROACTIVE_OODA_QUIET_HOURS_END` / `EA_PROACTIVE_OODA_QUIET_HOURS_TIMEZONE`: optional local quiet-hours window; matching non-high-priority digests are deferred without marking refs as notified
- `EA_PROACTIVE_OODA_QUIET_HOURS_ALLOW_HIGH_PRIORITY`: allow high-priority proactive digests through quiet hours, default `1`
- `EA_PROACTIVE_OODA_INTERRUPTION_BUDGET_LIMIT`: optional rolling-window notification cap; exhausted budgets defer the digest without marking refs as notified, default `0` disabled
- `EA_PROACTIVE_OODA_INTERRUPTION_BUDGET_WINDOW_HOURS`: rolling interruption-budget window, default `24`
- `EA_PROACTIVE_OODA_INTERRUPTION_BUDGET_ALLOW_HIGH_PRIORITY`: allow high-priority proactive digests through the interruption budget, default `1`
- `EA_PROACTIVE_OODA_TELEGRAM_CHAT_ID`: direct Telegram fallback chat id when the full app adapter is unavailable
- `--skip-observation-source` / `--skip-workspace-source`: runner/verifier flags for isolated dry-runs; the default runtime attempts both

Generic discovery example:

```bash
EA_PROACTIVE_OODA_DISCOVERY_JSON='{"sources":[{"type":"rss","url":"https://example.com/feed.xml","channel":"market_watch","counterparty":"Example"}]}' \
PYTHONPATH=ea .venv/bin/python scripts/run_proactive_ooda.py --dry-run --pretty
```

Teable discovery example:

```bash
EA_PROACTIVE_OODA_DISCOVERY_JSON='{"sources":[{"type":"teable","ref":"tbl_exec_signals","channel":"teable_admin","signal_type":"admin_signal","field_map":{"title":"Task","summary":"Brief","counterparty":"Owner","due_at":"Due"}}]}' \
PYTHONPATH=ea .venv/bin/python scripts/run_proactive_ooda.py --dry-run --pretty
```

The runner can also be tested from a static signal feed:

```bash
PYTHONPATH=ea .venv/bin/python scripts/run_proactive_ooda.py --signals-json signals.json --dry-run --pretty
```

Opportunity rule example:

```bash
EA_PROACTIVE_OODA_OPPORTUNITY_RULES_JSON='{"rules":[{"id":"renewal-review","title":"Review renewal options","summary":"A renewal window is open; compare realistic alternatives before it becomes urgent.","trigger":{"kind":"always"},"action":"Prepare one approval packet with the best option and the default do-nothing consequence.","action_plan":["Check current constraints","Compare realistic options","Stage the recommended next step"],"stage":{"kind":"approval_packet","summary":"One reversible next step ready for approval.","artifacts":["shortlist","candidate_link_or_cart","approval_prompt"]},"external_action_policy":"Do not buy, book, send, cancel, or commit without explicit approval."}]}' \
PYTHONPATH=ea .venv/bin/python scripts/run_proactive_ooda.py --dry-run --pretty
```
Snapshot pruning is available via `scripts/prune_openapi.sh` or `make openapi-prune`.
Endpoint inventory can be printed via `scripts/list_endpoints.sh` or `make endpoints`.
Version fingerprint can be printed via `scripts/version_info.sh` or `make version-info`.
`scripts/version_info.sh` still prints milestone capability-status counts and release tags from `MILESTONE.json` as delivery history, but EA flagship release claims now come from `EA_FLAGSHIP_TRUTH_PLANE.md`, `EA_FLAGSHIP_RELEASE_GATE.json`, and `EA_FLAGSHIP_RELEASE_GATE.generated.json`.
Operator summary can be printed via `scripts/operator_summary.sh` or `make operator-summary`.
The operator summary includes smoke, readiness, CI parity, release/support, and task-archive shortcuts.
It also includes the standalone WhatsApp Web action-processor readiness check via `make verify-whatsapp-web-action-processor-readiness`, so runtime health can be distinguished from live EPUB delivery evidence. For the published link itself, `make verify-whatsapp-audiobook-public-share-playback` proves the shared audiobook route still plays audio in a real browser session.
It also prints the long-running goal posture through the `detect`, `decide`, `deliver`, `recover`, and `prove` lenses, using the current local receipts where they exist and explicit commands where they do not.
The same posture can be materialized and verified explicitly via `make materialize-continuous-improvement-goal-posture` and `make verify-continuous-improvement-goal-posture`.
`bash scripts/operator_summary.sh --help` prints the usage contract and is included in `make operator-help`.
Operator script usage index can be printed via `make operator-help`.
Endpoint/version/OpenAPI helper scripts also expose `--help` and are included in `make operator-help`.
`make operator-help` also includes the hard-exit and LTD verifier scripts, so the release-gate lane uses the same help surface as deploy and smoke.
Support bundle export is available via `scripts/support_bundle.sh` or `make support-bundle`.
Support bundles apply baseline redaction for common secret/token/password patterns.
Support bundles always include redacted `ea.source_dirty_groups.v1` JSON from `make inspect-source-dirty-groups` plus the `ea.source_dirty_groups_verifier.v1` result, so clean-receipt blockers can be handed off without losing the affected source groups or their contract validity.
Run `make verify-source-dirty-groups` before handoff when you need to prove the dirty-source grouping report itself is internally consistent.
For focused clean-receipt triage, run `scripts/inspect_source_dirty_groups.py --list-categories` first, then drill into one group with `scripts/inspect_source_dirty_groups.py --category services --limit 20`.
Set `SUPPORT_INCLUDE_DB=0` to skip DB logs in support bundle generation.
Set `SUPPORT_INCLUDE_API=0` to skip API logs in support bundle generation.
Set `SUPPORT_INCLUDE_DB_VOLUME=0` to skip ea-db mount/volume attribution in support bundles.
Set `SUPPORT_INCLUDE_DB_SIZE=0` to skip DB size snapshots in support bundle generation.
Set `SUPPORT_DB_SIZE_LIMIT=<n>` to control top-table count in DB size snapshots.
Set `SUPPORT_INCLUDE_QUEUE=0` to skip queued-task snapshot in support bundles.
Set `SUPPORT_BUNDLE_PREFIX=<tag>` to customize support bundle filenames.
Set `SUPPORT_BUNDLE_TIMESTAMP_FMT=<date format>` to customize bundle timestamp formatting.
HTTP script host-port resolution details are documented at the top of `RUNBOOK.md`.
Task archive rotation is available via `scripts/archive_tasks.sh` or `make tasks-archive`; it now operates on the local ignored `TASKS_WORK_LOG.md` / `TASKS_ARCHIVE.md` files when present.
Retention pruning dry-runs are available via `scripts/db_retention.sh` or `make db-retention` (`EA_RETENTION_PROFILE=aggressive|standard|conservative`, optional `EA_RETENTION_TABLES`/`EA_RETENTION_SKIP_TABLES` filters).
DB size inspection supports optional schema/sort/prefix/size scoping via `EA_DB_SIZE_SCHEMA=<schema>`, `EA_DB_SIZE_SORT_KEY=total|table|index`, `EA_DB_SIZE_TABLE_PREFIX=<prefix>`, and `EA_DB_SIZE_MIN_MB=<n>`.
The Compose Postgres volume is `ea_pgdata`, mounted at `/var/lib/postgresql/data` in `ea-db`; large host paths under `/var/lib/docker/volumes/.../ea_pgdata` are on-disk Postgres state, not RAM.
Support bundles now include the expected volume name/mount plus live `ea-db` mount inspection output by default, so host-disk investigations start from captured evidence instead of guesswork.
Script help contract smoke is available via `scripts/smoke_help.sh` or `make smoke-help`.
`bash scripts/smoke_help.sh --help` is included in `make operator-help`.
Release smoke aggregate is available via `make release-smoke`.
Postgres-backed smoke run is available via `scripts/smoke_postgres.sh` or `make smoke-postgres`; the script now force-recreates `ea-api` when it rebuilds so host smoke never reuses stale API containers.
Postgres-backed repository contract tests are available via `scripts/test_postgres_contracts.sh` or `make test-postgres-contracts`; the current matrix covers artifacts, channel runtime, approvals, policy decisions, and task contracts.
Legacy migration-regression smoke is available via `bash scripts/smoke_postgres.sh --legacy-fixture` or `make smoke-postgres-legacy`.
The script targets an isolated smoke database (`EA_SMOKE_DB`, default `ea_smoke_runtime`) and restores local `.env` state after the run.
Local CI-parity compile checks can be run via `make ci-local`.
One-command local CI gate bundle is available via `make ci-gates`; it includes release asset verification, flagship release-readiness verification, whole-project gold-map verification, and generated release artifact cleanliness after the full memory-backed test suite.
Combined local API+Postgres parity run is available via `make ci-gates-postgres`.
Combined local API+Postgres legacy-migration parity run is available via `make ci-gates-postgres-legacy`.
Runtime deploy hard gate is available via `make runtime-hard-exit-gates`; `scripts/deploy.sh` runs it by default after health goes green unless `EA_RUN_RUNTIME_HARD_EXIT_GATES=0`. This live bundle uses the deploy-safe API smoke lane, the authoritative live-runtime release verifier, and Pocket archive verification; when `MEMORIAL` mode is enabled it also runs `verify_memorial_runtime_overlay` plus `verify_project_mode_runtime.py --mode memorial` automatically so a memorial deploy cannot finish with the overlay absent or with the mounted public memorial surface broken. The deeper principal contract smoke stays in `make hard-exit-gates`.
Full flagship hard exit gate is available via `make hard-exit-gates`; it runs the full pytest suite plus release preflight, Postgres contract/smoke lanes, principal API smoke, and Pocket archive verification.
Aggregate LTD release gates are available via `make ltd-release-gates`; the bundle includes critical runtime entries, the flagship verified subset, and governed provider-lane receipts.
Release asset integrity can be checked via `scripts/verify_release_assets.sh` or `make verify-release-assets`. That path now also enforces `make verify-release-authority` plus `make verify-release-authority-runtime-authoritative`, so generated receipts alone cannot stand in for deploy truth or a non-authoritative live runtime.
To regenerate the full local release-truth bundle in one pass, use `make materialize-release-assets`; it now materializes deploy context before the release manifest and release-authority status.
Whole-project gold-map integrity can be checked via `scripts/verify_whole_project_gold_map.py` or `make verify-whole-project-gold-map`; when green, it means the current EA-controlled receipt set is coherent. Owning repos remain authoritative for their own product planes. For memorial presentation readiness, run `make verify-memorial-deploy-readiness` before deploy so release-authority drift or a non-memorial runtime posture fails closed, then `make verify-memorial-runtime-overlay` so `/health/live` proves the memorial overlay is actually mounted, then `make verify-project-mode-runtime-memorial` so the mounted public memorial surface itself is reachable and correctly wired, then run `make verify-memorial-voice-stability` against the deployed stack.
Docs-focused alias for the same check: `make docs-verify`.
Docs + operator help aggregate: `make release-docs`.
Release preflight aggregate is available via `make release-preflight`; it includes `make verify-runtime-supply-chain`, `make verify-release-authority`, `make verify-release-authority-runtime-authoritative`, `make verify-flagship-release-readiness`, `make verify-whole-project-gold-map`, and generated release artifact cleanliness so a green receipt cannot hide a blocked weekly pulse, Fleet journey gate, overbroad gold claim, weak deploy authority, non-authoritative live runtime, runtime supply-chain drift, or dirty regenerated receipt.
For real-browser gates on a fresh host, install the browser dependency first with `python -m playwright install --with-deps chromium`.
Recommended sequencing: run `make release-docs` before `make release-preflight`.
One-command local readiness check: `make all-local`.
`make all-local` is a lighter local readiness pass; it still verifies release assets, flagship readiness, and generated release artifact cleanliness, but it does not require release-claim authority. Use `make release-preflight` for release-stage smoke + operator checks.
CI gate sequence is documented in `RUNBOOK.md` and includes the API gate bundle (`smoke-help`, `ci-local`, `test-api`, release-asset verification, flagship release-readiness verification, generated release artifact cleanliness), Postgres-backed smoke and repository-contract jobs (`scripts/smoke_postgres.sh`, `scripts/test_postgres_contracts.sh`), and a legacy migration-regression job (`bash scripts/smoke_postgres.sh --legacy-fixture`).
Shell script lint config is tracked in `.shellcheckrc`.
