# Runtime Runbook

All runtime scripts that call HTTP endpoints resolve host port in this order:
1. `EA_HOST_PORT` from current shell env
2. `EA_HOST_PORT` from `.env`
3. fallback `8090`

## API Contract Summary

Hosted GitHub Actions workflows are intentionally absent from this repo. Operator verification is local-only and is expected to run through the Make gate bundles: `make ci-gates`, `make ci-gates-postgres`, `make ci-gates-postgres-legacy`, and `make release-preflight`.

`X-Forwarded-Host` is fail-closed by default. Set `PROPERTYQUARRY_TRUST_X_FORWARDED_HOST=1` only when a trusted ingress or tunnel is the sole caller rewriting that header; otherwise public canonicals, callback origins, and public host routing use the direct request host.

`X-Forwarded-For` and `CF-Connecting-IP` are also fail-closed for public identity helpers. Set `PROPERTYQUARRY_TRUST_X_FORWARDED_FOR=1` only when the runtime is actually behind a trusted ingress; otherwise public rate-limit identity stays bound to the direct client host.

That same rule now covers public memorial rate-limit identity as well as the shared public-results/public-documents/channel helpers.

`EA_ALLOW_LOOPBACK_NO_AUTH=1` only bypasses API-token auth for loopback-local principal access. Operator-only routes still require an active operator profile; local loopback requests no longer become operator context automatically.

`EA_TRUST_AUTHENTICATED_PRINCIPAL_HEADER=1` only permits authenticated principal-header override from loopback-local requests. Keep it as a local fixture/testing switch, not a shared-runtime impersonation path.

Browser setup also ignores the old advanced principal override path. Without a verified access identity, `/get-started` and `/setup/*` only operate on the deployment default workspace.

| Method | Route | Success | Error contracts |
|---|---|---|---|
| GET | `/health` | `200` | n/a |
| GET | `/health/live` | `200` | n/a |
| GET | `/health/ready` | `200` | `503 not_ready:*` |
| GET | `/version` | `200` | n/a |
| GET | `/health/release-authority` | `200` | n/a |

`/version` also reports `release_authority_state`, `release_authority_posture`, and `release_authority_source` so the compact runtime probe shows whether release truth is coming from the published status artifact or manifest fallback.
| POST | `/v1/rewrite/artifact` | `200`, `202 awaiting_approval`, `202 awaiting_human`, `202 queued` | `400 text is required`, `403 principal_scope_mismatch`, `403 policy_denied:*` (including `tool_not_allowed`) |
| GET | `/v1/rewrite/artifacts/{artifact_id}` | `200` | `404 artifact_not_found`, `403 principal_scope_mismatch` (returns artifact content plus explicit `principal_id` ownership, originating `task_key`/`deliverable_type`, `mime_type`, `preview_text`, `storage_handle`, `body_ref`, and structured attachment metadata) |
| GET | `/v1/rewrite/receipts/{receipt_id}` | `200` | `404 receipt_not_found`, `403 principal_scope_mismatch` (returns proof metadata plus originating `task_key`/`deliverable_type`) |
| GET | `/v1/rewrite/run-costs/{cost_id}` | `200` | `404 run_cost_not_found`, `403 principal_scope_mismatch` (returns cost metadata plus originating `task_key`/`deliverable_type`) |
| GET | `/v1/rewrite/sessions/{session_id}` | `200` | `404 session not found`, `403 principal_scope_mismatch` (returns events + steps + queue items + receipts + artifacts + costs + human task packets, inline human task assignment history, `intent_skill_key`, self-describing artifact/proof task identity, resolved `skill_key`, human-task packet task identity, inline assignment-history task identity, `plan_compiled` event, computed reviewer routing hints, and supports `human_task_assignment_source`) |
| POST | `/v1/human/tasks` | `200` | `400 step_id_required`, `404 session_not_found`, `404 step_not_found`, `403 principal_scope_mismatch` (supports `resume_session_on_return=true` to move a linked step into `waiting_human`) |
| GET | `/v1/human/tasks/priority-summary` | `200` | validation `422`, `403 principal_scope_mismatch` (supports `status`, `role_required`, `operator_id`, `assigned_operator_id`, `assignment_state`, `assignment_source`, and `overdue_only`) |
| GET | `/v1/human/tasks` | `200` | validation `422`, `403 principal_scope_mismatch` (supports `role_required`, `priority`, `assigned_operator_id`, `assignment_state`, `assignment_source`, `overdue_only`, and `sort=created_asc|created_desc|last_transition_desc|priority_desc_created_asc|sla_due_at_asc|sla_due_at_asc_last_transition_desc`) |
| GET | `/v1/human/tasks/backlog` | `200` | validation `422` (supports `priority`, `assignment_state`, `assignment_source` and `sort=created_asc|created_desc|last_transition_desc|priority_desc_created_asc|sla_due_at_asc|sla_due_at_asc_last_transition_desc`) |
| GET | `/v1/human/tasks/unassigned` | `200` | validation `422` (supports `priority`, `assignment_source` and `sort=created_asc|created_desc|last_transition_desc|priority_desc_created_asc|sla_due_at_asc|sla_due_at_asc_last_transition_desc`) |
| GET | `/v1/human/tasks/mine` | `200` | validation `422` (supports `priority`, `assignment_source` and `sort=created_asc|created_desc|last_transition_desc|priority_desc_created_asc|sla_due_at_asc|sla_due_at_asc_last_transition_desc`) |
| POST | `/v1/human/tasks/operators` | `200` | validation `422`, `403 principal_scope_mismatch` |
| GET | `/v1/human/tasks/operators` | `200` | validation `422`, `403 principal_scope_mismatch` |
| GET | `/v1/human/tasks/operators/{operator_id}` | `200` | `404 operator_profile_not_found` |
| POST | `/v1/human/tasks/{human_task_id}/assign` | `200` | `404 human_task_not_found`, `409 human_task_not_assignable` |
| GET | `/v1/human/tasks/{human_task_id}/assignment-history` | `200` | `404 human_task_not_found`, validation `422` (supports `event_name`, `assigned_operator_id`, `assigned_by_actor_id`, `assignment_source`, and returns originating `task_key`/`deliverable_type`) |
| GET | `/v1/human/tasks/{human_task_id}` | `200` | `404 human_task_not_found` |
| POST | `/v1/human/tasks/{human_task_id}/claim` | `200` | `404 human_task_not_found`, `409 human_task_not_claimable` |
| POST | `/v1/human/tasks/{human_task_id}/return` | `200` | `404 human_task_not_found`, `409 human_task_not_returnable` |
| GET | `/v1/policy/decisions/recent` | `200` | `403 principal_scope_mismatch`, `404 session_not_found` when `session_id` is scoped to another principal |
| POST | `/v1/policy/evaluate` | `200` | validation `422`, `403 principal_scope_mismatch` |
| GET | `/v1/policy/approvals/pending` | `200` | n/a (pending rows include originating `task_key`/`deliverable_type` and stay scoped to the effective request principal) |
| GET | `/v1/policy/approvals/history` | `200` | `403 principal_scope_mismatch`, `404 session_not_found` when `session_id` is scoped to another principal (history rows include originating `task_key`/`deliverable_type`) |
| POST | `/v1/policy/approvals/{approval_id}/approve` | `200` | `404 approval_not_found`, `403 principal_scope_mismatch` (decision row includes originating `task_key`/`deliverable_type`) |
| POST | `/v1/policy/approvals/{approval_id}/deny` | `200` | `404 approval_not_found`, `403 principal_scope_mismatch` (decision row includes originating `task_key`/`deliverable_type`) |
| POST | `/v1/policy/approvals/{approval_id}/expire` | `200` | `404 approval_not_found`, `403 principal_scope_mismatch` (decision row includes originating `task_key`/`deliverable_type`) |
| POST | `/v1/observations/ingest` | `200` | validation `422` (supports source/external/dedupe/auth/raw payload pointers) |
| GET | `/v1/observations/recent` | `200` | validation `422` |
| POST | `/v1/delivery/outbox` | `200` | validation `422` (supports idempotency keys) |
| GET | `/v1/delivery/outbox/pending` | `200` | validation `422` |
| POST | `/v1/delivery/outbox/{delivery_id}/sent` | `200` | `404 delivery_not_found` |
| POST | `/v1/delivery/outbox/{delivery_id}/failed` | `200` | `404 delivery_not_found` |
| POST | `/v1/channels/telegram/ingest` | `200` | validation `422` |
| POST | `/v1/tools/registry` | `200` | validation `422` |
| GET | `/v1/tools/registry` | `200` | validation `422` |
| GET | `/v1/tools/registry/{tool_name}` | `200` | `404 tool_not_found` |
| POST | `/v1/tools/execute` | `200` | `404 tool_not_registered:*`, `409 tool_execution_failed` |
| POST | `/v1/connectors/bindings` | `200` | validation `422` |
| GET | `/v1/connectors/bindings` | `200` | validation `422` |
| POST | `/v1/connectors/bindings/{binding_id}/status` | `200` | `404 binding_not_found` |
| POST | `/v1/tasks/contracts` | `200` | validation `422` |
| GET | `/v1/tasks/contracts` | `200` | validation `422` |
| GET | `/v1/tasks/contracts/{task_key}` | `200` | `404 task_contract_not_found` |
| POST | `/v1/skills` | `200` | validation `422` |
| GET | `/v1/skills` | `200` | validation `422` (supports `provider_hint=<value>` to filter the catalog by LTD-backed provider hints such as `BrowserAct` or `1min.AI`) |
| GET | `/v1/skills/{skill_key}` | `200` | `404 skill_not_found` |
| POST | `/v1/plans/compile` | `200` | validation `422`, `403 principal_scope_mismatch` (accepts either `task_key` or `skill_key`) |
| POST | `/v1/plans/execute` | `200`, `202 awaiting_approval`, `202 awaiting_human`, `202 queued` | validation `422`, `403 principal_scope_mismatch`, `403 policy_denied:*` (accepts either `task_key` or `skill_key`) |
| GET | `/v1/evidence/objects` | `200` | validation `422`, `403 principal_scope_mismatch` (supports `artifact_id`, `session_id`, and `evidence_ref`; returns stable `citation_handle` values for evidence-pack artifacts) |
| GET | `/v1/evidence/objects/{evidence_id}` | `200` | `404 evidence_object_not_found` |
| POST | `/v1/evidence/merge` | `200` | `400 evidence_ids_required`, `404 evidence_object_not_found:*`, `403 principal_scope_mismatch` |
| POST | `/v1/memory/candidates` | `200` | validation `422` |
| GET | `/v1/memory/candidates` | `200` | validation `422` |
| POST | `/v1/memory/candidates/{candidate_id}/promote` | `200` | `404 memory_candidate_not_found` |
| POST | `/v1/memory/candidates/{candidate_id}/reject` | `200` | `404 memory_candidate_not_found` |
| GET | `/v1/memory/items` | `200` | validation `422` |
| GET | `/v1/memory/items/{item_id}` | `200` | `404 memory_item_not_found` |
| POST | `/v1/memory/entities` | `200` | validation `422` |
| GET | `/v1/memory/entities` | `200` | validation `422` |
| GET | `/v1/memory/entities/{entity_id}` | `200` | `404 entity_not_found` |
| POST | `/v1/memory/relationships` | `200` | validation `422` |
| GET | `/v1/memory/relationships` | `200` | validation `422` |
| GET | `/v1/memory/relationships/{relationship_id}` | `200` | `404 relationship_not_found` |
| POST | `/v1/memory/commitments` | `200` | validation `422` |
| GET | `/v1/memory/commitments` | `200` | validation `422` |
| GET | `/v1/memory/commitments/{commitment_id}` | `200` | `404 commitment_not_found` |
| POST | `/v1/memory/authority-bindings` | `200` | validation `422` |
| GET | `/v1/memory/authority-bindings` | `200` | validation `422` |
| GET | `/v1/memory/authority-bindings/{binding_id}` | `200` | `404 authority_binding_not_found` |
| POST | `/v1/memory/delivery-preferences` | `200` | validation `422` |
| GET | `/v1/memory/delivery-preferences` | `200` | validation `422` |
| GET | `/v1/memory/delivery-preferences/{preference_id}` | `200` | `404 delivery_preference_not_found` |
| POST | `/v1/memory/follow-ups` | `200` | validation `422` |
| GET | `/v1/memory/follow-ups` | `200` | validation `422` |
| GET | `/v1/memory/follow-ups/{follow_up_id}` | `200` | `404 follow_up_not_found` |
| POST | `/v1/memory/deadline-windows` | `200` | validation `422` |
| GET | `/v1/memory/deadline-windows` | `200` | validation `422` |
| GET | `/v1/memory/deadline-windows/{window_id}` | `200` | `404 deadline_window_not_found` |
| POST | `/v1/memory/stakeholders` | `200` | validation `422` |
| GET | `/v1/memory/stakeholders` | `200` | validation `422` |
| GET | `/v1/memory/stakeholders/{stakeholder_id}` | `200` | `404 stakeholder_not_found` |
| POST | `/v1/memory/decision-windows` | `200` | validation `422` |
| GET | `/v1/memory/decision-windows` | `200` | validation `422` |
| GET | `/v1/memory/decision-windows/{decision_window_id}` | `200` | `404 decision_window_not_found` |
| POST | `/v1/memory/communication-policies` | `200` | validation `422` |
| GET | `/v1/memory/communication-policies` | `200` | validation `422` |
| GET | `/v1/memory/communication-policies/{policy_id}` | `200` | `404 communication_policy_not_found` |
| POST | `/v1/memory/follow-up-rules` | `200` | validation `422` |
| GET | `/v1/memory/follow-up-rules` | `200` | validation `422` |
| GET | `/v1/memory/follow-up-rules/{rule_id}` | `200` | `404 follow_up_rule_not_found` |
| POST | `/v1/memory/interruption-budgets` | `200` | validation `422` |
| GET | `/v1/memory/interruption-budgets` | `200` | validation `422` |
| GET | `/v1/memory/interruption-budgets/{budget_id}` | `200` | `404 interruption_budget_not_found` |
| POST | `/v1/memory/context-pack` | `200` | validation `422`, `403 principal_scope_mismatch` |

Error envelope for failures:
- `{ "error": { "code": "...", "message": "...", "details": ..., "correlation_id": "..." } }`

Auth:
- Set `EA_API_TOKEN=<token>` to require auth for all non-health routes.
- Use `Authorization: Bearer <token>` or `X-API-Token: <token>`.
- Use `X-EA-Principal-ID: <principal>` for principal-scoped rewrite/session/artifact/receipt/run-cost, plan-compile/execute, connector, human-task, and memory routes; if omitted, `EA_DEFAULT_PRINCIPAL_ID` (default `principal-default`) is used.
- On those routes, body/query `principal_id` remains a compatibility field only and mismatches fail with `403 principal_scope_mismatch`.
- `GET /v1/models` returns both the public EA aliases and the currently configured upstream model IDs, so Codex can target concrete provider models when needed.
- `EA_RESPONSES_PROVIDER_ORDER`, `EA_RESPONSES_FAST_PROVIDER_ORDER`, `EA_RESPONSES_CHEAP_PROVIDER_ORDER`, `EA_RESPONSES_GROUNDWORK_PROVIDER_ORDER`, and `EA_RESPONSES_HARD_PROVIDER_ORDER` tune normal, fast, cheap/background, groundwork, and hard lane provider order without patching code; keep the 1minAI manager first and Gemini/Vertex as fallback unless an explicit incident runbook says otherwise. Aliases such as `1min` and `magicx` normalize to runtime provider keys.
- `GET /v1/responses/_provider_health` and `GET /v1/codex/profiles` expose account-name-only provider attribution plus 1min owner metadata matched by hash or stable slot/account identifiers, latest explicit probe evidence, 1min.AI depletion, observed per-slot consumption (`observed_consumed_credits`, `observed_success_count`), rolling burn-rate, and deleted-key telemetry (`remaining_credits`, `required_credits`, `estimated_remaining_credits_total`, `remaining_percent_of_max`, `estimated_burn_credits_per_hour`, `estimated_hours_remaining_at_current_pace`) without leaking raw API keys.
- `POST /v1/providers/onemin/probe-all` sends one live low-volume request to each selected 1min slot, records `last_probe_result`, and updates deleted/depleted/rate-limited evidence immediately instead of waiting for incidental runtime traffic.
- `python3 scripts/sync_onemin_owner_ledger.py --write` re-hashes the current `ONEMIN_AI_API_KEY*` values plus any `ONEMIN_DIRECT_API_KEYS_JSON(_FILE)` manifest entries into `config/onemin_slot_owners.json` and carries owner labels/emails forward by slot/account when the runtime key set rotates.
- The template-backed 1min BrowserAct refresh lane now accepts a generic rotating proxy through `EA_UI_BROWSER_PROXY_SERVER`, `EA_UI_BROWSER_PROXY_USERNAME`, `EA_UI_BROWSER_PROXY_PASSWORD`, and `EA_UI_BROWSER_PROXY_BYPASS`; use `ONEMIN_BROWSERACT_MAX_ACCOUNTS_PER_REFRESH` plus `EA_ONEMIN_BILLING_REFRESH_MIN_INTERVAL_SECONDS` when you want one operator-triggered refresh cycle to sweep the full slot set without the old cadence throttle.
- FastestVPN can back that lane through [docker-compose.fastestvpn.yml](docker-compose.fastestvpn.yml): place FastestVPN OpenVPN profiles under `vpn/fastestvpn/`, or fetch them with `scripts/bootstrap_fastestvpn_configs.sh`, then deploy with `EA_ENABLE_FASTESTVPN=1 bash scripts/deploy.sh --compose-override docker-compose.fastestvpn.yml`. If you use `scripts/deploy.sh`, keep that overlay explicit with `EA_ENABLE_FASTESTVPN=1`. The overlay uses `ea-docker-socket-proxy` for operator Docker control, constrains that sidecar with dropped capabilities, `no-new-privileges`, read-only rootfs, and bounded memory/PID limits, keeps the operator image on its default non-root user, mounts only `docker-compose.yml`, `docker-compose.fastestvpn.yml`, and `vpn/fastestvpn/` into the runtime services, drops all ambient Linux capabilities, and applies read-only rootfs, `no-new-privileges`, and bounded memory/PID limits to the operator services. Use `scripts/rotate_fastestvpn_proxy.sh` to recreate the proxy on a fresh FastestVPN exit profile before a full 1min BrowserAct refresh; it uses `docker compose up -d --no-build --force-recreate --no-deps` so the refresh does not rebuild the runtime.
- `EA_RESPONSES_ONEMIN_INCLUDED_CREDITS_PER_KEY`, `EA_RESPONSES_ONEMIN_BONUS_CREDITS_PER_KEY`, `EA_RESPONSES_ONEMIN_DELETED_KEY_QUARANTINE_SECONDS`, `EA_RESPONSES_ONEMIN_OWNER_LEDGER_PATH`, `EA_RESPONSES_ONEMIN_PROBE_MODEL`, and `EA_RESPONSES_ONEMIN_PROBE_TIMEOUT_SECONDS` tune those credit, owner-ledger, and explicit-probe diagnostics.
- `EA_RESPONSES_MAGICX_HEALTH_CHECK`, `EA_RESPONSES_MAGICX_HEALTH_INTERVAL_SECONDS`, and `EA_RESPONSES_MAGICX_HEALTH_TIMEOUT_SECONDS` enable and tune the live Magicx fallback probe so provider health reflects a real upstream readiness check.
- After a BrowserAct inventory refresh, `bash scripts/refresh_ltds_from_inventory.sh --input <inventory.json> --write` can rewrite the `## Discovery Tracking` section in [LTDs.md](LTDs.md) from the structured inventory artifact/output instead of editing the markdown table by hand.
- When the local API is already running, `bash scripts/refresh_ltds_via_api.sh --binding-id <browseract-binding-id> --service-name BrowserAct --service-name Teable --write` can execute the BrowserAct-backed `ltd_inventory_refresh` skill via `/v1/plans/execute`, save the raw inventory payload if requested, and update [LTDs.md](LTDs.md) in one pass.
- `python3 scripts/verify_ltd_critical_entries.py` is the hard verifier for the currently depended-on LTD lanes. It fails closed if [LTDs.md](LTDs.md) or the live env drift away from the required `1min.AI`, `Prompt Architects`, BrowserAct, and Teable facts.
- `python3 scripts/verify_ltd_flagship_subset.py` is the broader release gate for the current flagship verified subset. It intentionally covers a named subset instead of pretending all `manual_seeded` or `missing` LTD rows are already proven.
- `python3 scripts/verify_ltd_provider_lanes.py` writes governed provider-lane receipts with off-switches, source-of-truth boundaries, allowed/forbidden inputs, and missing proof checks.
- `python3 scripts/materialize_poppy_draft_packet.py --source-packet <packet.json> --draft-output <draft.txt>` turns a manually copied Poppy draft into a hash-only receipt. It accepts only public or operator-approved source packets, leaves `runtime_enabled=false`, and requires human review before any source-controlled content change.
- `make ltd-release-gates` runs all LTD release verifiers together.
- `make verify-ltd-critical-entries`, `make verify-ltd-flagship-subset`, and `make verify-ltd-provider-lanes` are the corresponding operator entrypoints.

Runtime mode:
- Set `EA_RUNTIME_MODE=prod` for durable environments; the app will fail fast instead of falling back from `EA_STORAGE_BACKEND=auto` or `memory` to in-process storage.
- In `prod`, workspace-access token binding must resolve from `EA_PUBLIC_APP_BASE_URL`, `EA_GOOGLE_OAUTH_REDIRECT_URI`, or `EA_WORKSPACE_ACCESS_TOKEN_ISSUER`; keep `EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE` and `EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION` explicit so session cookies and workspace links stay verifiable across deploys. Placeholder or loopback binding origins such as `https://example.test`, `https://property.example.test`, or `http://localhost` are rejected.
- `scripts/deploy.sh` enforces that preflight now: in `prod` it requires real production auth (`EA_API_TOKEN` or Cloudflare Access via `EA_CF_ACCESS_TEAM_DOMAIN` + `EA_CF_ACCESS_AUD`), requires a real `EA_SIGNING_SECRET`, refuses placeholder or loopback token-binding origins, and refuses missing or placeholder `EA_WORKSPACE_ACCESS_TOKEN_AUDIENCE` / `EA_WORKSPACE_ACCESS_TOKEN_KEY_VERSION` values before it recreates containers.
- The EA core compose publishes its host ports only on `127.0.0.1`, and `docker-compose.prod.yml` does not widen those bindings. If the runtime should be reachable from outside the host, add an explicit ingress override such as `docker-compose.cloudflared.yml` instead of changing the core bind posture.
- `docker-compose.property.yml` now follows that same default posture: the property API bind stays on `127.0.0.1`, and the property API, scheduler, and database containers run with dropped capabilities, `no-new-privileges`, and bounded memory/PID limits.
- The Cloudflare tunnel override keeps `ea-cloudflared` digest-pinned and constrained with dropped capabilities, `no-new-privileges`, and bounded memory/PID limits, so ingress stays on the same hardening path as the rest of the runtime.
- In `prod`, legacy authenticated runtime surfaces stay off by default as well. Keep `EA_ENABLE_LEGACY_RUNTIME_SURFACES=0` for EA core product deploys, and only opt in when a governed migration or operator-only lane still needs `/v1/memory/*`, `/v1/rewrite/*`, `/v1/channels/*`, or `/v1/responses*`.
- For the durable runtime profile, run `bash scripts/deploy.sh`.

Memorial shadow STT:
- The memorial `speech-transcribe` path can run a shadow STT lane for user-question audio only; it never ships Manfred's answer audio, private memorial memory, or authority truth to the provider.
- Current supported provider is BlipAI. Runtime calls it in shadow-only mode, scores the returned correction, and can replace only the user transcript, never the answer policy.
- If BlipAI returns `401`/`403`, the runtime attempts one refresh-token recovery before entering cooldown.
- Refreshed BlipAI tokens are persisted locally at `state/memorial_blipai_shadow_stt_tokens.json` under the configured memorial state directory unless `EA_MEMORIAL_BLIPAI_TOKEN_STATE_PATH` overrides that path.
- If BlipAI returns `401`, `403`, or `429` after refresh handling, the lane enters cooldown for `EA_MEMORIAL_SHADOW_STT_ERROR_COOLDOWN_SECONDS` and primary STT remains authoritative.
- The memorial remains fail-closed without BlipAI credentials: primary STT still answers; shadow STT simply reports `url_missing`, `provider_cooldown_active`, or another bounded reason.

Policy notes:
- Rewrite policy denies empty input, oversized input, and disallowed tool usage.
- Rewrite policy requires approval for explicit approval classes, long inputs, and high-risk/high-budget or external-send actions.
- `POST /v1/policy/evaluate` provides a direct HTTP path for previewing external-send approval requirements, including the step/authority/review metadata that now drives the queued policy step, and its body `principal_id` is only a compatibility filter against the effective request principal.
- Approving a paused rewrite resumes execution immediately on the current scaffold, so the session should move from `awaiting_approval` to `completed` with an artifact, receipt, and run-cost row.
- Approval-required rewrites now return `202` with `session_id`, `approval_id`, `status=awaiting_approval`, and `next_action=poll_or_subscribe` instead of a `409` error contract.
- Allowed and approved rewrites now pass through durable `execution_queue` rows first; the current API path drains that queue inline, while non-API runner roles can drain it as workers.
- The current rewrite scaffold now executes as three explicit queued steps: `step_input_prepare`, `step_policy_evaluate`, and `step_artifact_save`.
- `policy_decision` is now emitted from the queued `step_policy_evaluate` handler after `input_prepared`, so the ledger order matches runtime execution before approval or block transitions are recorded.
- `POST /v1/plans/compile` exposes `depends_on`, `input_keys`, and `output_keys`, and queue advancement now enqueues every currently ready step from satisfied dependency edges instead of parent-linked step order while paused sessions stop further leasing.
- Planner/orchestrator startup now validates duplicate step keys, unknown dependency keys, and dependency cycles before any session rows are started, so invalid plan graphs fail before the queue runtime can lease them.
- The queue runtime now only merges declared dependency inputs and fails missing declared outputs before a step can complete, so `input_keys` / `output_keys` contracts are enforced instead of remaining descriptive metadata only.
- Session step `parent_step_id` now mirrors only real single-dependency edges; multi-prerequisite join steps stay parentless and rely on `dependency_keys` plus `dependency_states` for graph truth.
- `POST /v1/plans/compile` and the queued session step input payloads now also expose `owner`, `authority_class`, `review_class`, `failure_strategy`, `timeout_budget_seconds`, `max_attempts`, and `retry_backoff_seconds`, so operator tooling can see who owns each step and what runtime posture it expects before deeper graph execution lands.
- `POST /v1/plans/execute` now reuses that same compiled task-contract runtime for non-`rewrite_text` artifact flows, accepts structured `input_json` plus `context_refs` in addition to the legacy `text` convenience field, injects synthesized `context_pack` payloads from principal-scoped memory reasoning, and lets stakeholder briefings and similar executive contracts run through the queue-backed graph without a rewrite-only entrypoint.
- `POST /v1/memory/context-pack` exposes the same memory reasoning envelope directly for operators, including promoted-memory signals, conflict rows, commitment-risk rows, and unresolved refs for the request principal.
- `POST /v1/plans/execute` now also returns the same first-class `202 awaiting_approval` and `202 awaiting_human` workflow contract as rewrite execution, and those generic task sessions resume through the shared approval and human-task endpoints.
- Rewrite creation and `POST /v1/plans/execute` now also return `202 queued` with `next_action=poll_or_subscribe` when a retryable step reschedules itself into the future (`retry_backoff_seconds>0`), so delayed queue retries stay async instead of surfacing `queued task did not execute`.
- Those paused generic task sessions keep graph-aware dependency metadata in `GET /v1/rewrite/sessions/{session_id}` too: approval-backed runs hold `step_artifact_save` in `waiting_approval` with satisfied dependencies, while human-review-backed runs leave downstream save steps queued behind `blocked_dependency_keys=["step_human_review"]` until the operator returns the packet.
- Tool and system step failures can now also honor `failure_strategy=retry`: the queue runtime reuses the same queue row, keeps `attempt_count` monotonic, records `step_retry_scheduled`, and delays the next lease by `retry_backoff_seconds` until `max_attempts` is exhausted.
- If that retried queue row is immediately eligible (`retry_backoff_seconds=0`), the inline create/approve/return paths now keep draining the same session until it reaches completion, pause, or terminal failure instead of surfacing `queued task did not execute` for a retry that was already ready to run.
- The execution ledger now uses an explicit `set_session_status(...)` transition API for nonterminal states (`queued`, `running`, `blocked`, `awaiting_approval`, `awaiting_human`, `failed`), so retry and pause/resume flows no longer look like session completion in code or metrics.
- Task-contract metadata can now override the built-in artifact and dispatch retry posture too: `budget_policy_json.artifact_failure_strategy|artifact_max_attempts|artifact_retry_backoff_seconds` tune `step_artifact_save`, while `dispatch_failure_strategy|dispatch_max_attempts|dispatch_retry_backoff_seconds` tune `step_connector_dispatch`.
- That same task-contract and skill metadata is now normalized into typed runtime policy models (`artifact_retry`, `dispatch_retry`, `human_review`, `memory_candidate`, `artifact_output`, and `skill_catalog`) before planner/runtime execution, so the branch-baseline workflow logic reads one canonical policy shape instead of unpacking ad-hoc `budget_policy_json` keys at each call site.
- Approval and human-task queue/detail payloads now stay self-describing for non-rewrite async work by returning the originating `task_key` and `deliverable_type` before the workflow completes.
- Rewrite creation and session/artifact/receipt/run-cost fetches now enforce the same request principal contract as the rest of the scoped surface, so foreign-principal fetch attempts fail with `403 principal_scope_mismatch` instead of exposing another execution thread.
- Session-bound `POST /v1/human/tasks` and `GET /v1/human/tasks?session_id=...` now enforce that the request principal matches the linked execution session principal too, so one principal cannot stitch packets onto or enumerate another principal's session thread via `session_id`.
- Task-contract metadata can now add a projected `step_human_review` branch by setting `budget_policy_json.human_review_role`, `human_review_priority`, `human_review_sla_minutes`, `human_review_auto_assign_if_unique`, `human_review_desired_output_json`, `human_review_authority_required`, `human_review_why_human`, and `human_review_quality_rubric_json`; the rewrite runtime auto-creates the linked human task packet with those routing and review-contract fields when that step executes, auto-assigns a unique exact reviewer when the flag is enabled, and a returned `final_text` payload now overrides the downstream artifact-save input.
- Task contracts can now also switch the compiled workflow skeleton with `budget_policy_json.workflow_template`; the built-in `artifact_then_dispatch` template emits `step_input_prepare -> step_artifact_save -> step_policy_evaluate -> step_connector_dispatch`, persists the artifact before approval, and resumes into `connector.dispatch` only after the approval-backed delivery gate is approved.
- Task contracts can now also use the generic `workflow_template=tool_then_artifact` macro plus `budget_policy_json.pre_artifact_tool_name=<tool>` to compile a reusable pre-artifact tool branch, and the supported BrowserAct slices prove both `browseract.extract_account_facts` and `browseract.extract_account_inventory` can run through `step_input_prepare -> ... -> step_artifact_save` without another one-off planner path.
- Task contracts can now also switch to `workflow_template=browseract_extract_then_artifact`, compiling `step_input_prepare -> step_browseract_extract -> step_artifact_save` so BrowserAct-backed account discovery can extract tier/email/status facts and persist them as a structured artifact in one queue-backed pass.
- `/v1/skills` now exposes a first-class executive skill catalog on top of those task contracts, preserving product metadata such as memory reads/writes, authority/tool/human/provider policy, evaluation cases, and workflow-template selection in the existing task-contract store; [SKILLS.md](SKILLS.md) tracks the current catalog and now includes the `chummer6_public_writer` and `chummer6_visual_director` lanes routed through the brain router with 1min.AI primary and Gemini fallback, the BrowserAct-backed `browseract_bootstrap_manager` for prompt-tool and page-extract templates, and the BrowserAct-backed `ltd_inventory_refresh` inventory skill alongside `meeting_prep`.
- `/v1/skills?provider_hint=<value>` now filters that catalog against nested `provider_hints_json`, so operator tooling can answer questions like “which skills rely on BrowserAct or 1min.AI?” without maintaining a second provider map outside the task-contract store.
- The runtime now also keeps typed read projections for task-contract policy (`TaskContractPolicyRecord`), product-facing skill metadata (`SkillCatalogRecord`), and provider posture (`ProviderBindingState`) so planner/catalog/provider code reads structured records instead of unpacking raw JSON blobs at every boundary.
- `/v1/plans/compile` and `/v1/plans/execute` now also project the resolved `skill_key`, so operator tooling can render the product-facing executive capability name without reverse-mapping every `task_key` client-side.
- `POST /v1/plans/compile` and `POST /v1/plans/execute` now also accept `skill_key` directly, so product-facing clients can compile or execute a skill without first resolving its backing `task_key`.
- `/v1/rewrite/sessions/{session_id}` plus direct artifact/receipt/run-cost reads now also project that same `skill_key`, so queue/runtime inspection stays aligned with the product-facing skill catalog once work has been executed.
- Chummer6 guide text generation is now intentionally EA-only on the planner side. It stays on the `ea-groundwork` lane so the brain router can use the 1min manager first and Gemini only as fallback; if that EA lane is unavailable, the worker hard-fails instead of drifting into Codex fallback.
- `python3 scripts/generate_browseract_content_templates.py` writes ready-to-edit BrowserAct packet and workflow JSON for the Economist, The Atlantic, NYTimes, ApproveThis, and MetaSurvey reader templates into `browseract_templates/` by default. Set `EA_BROWSERACT_CONTENT_TEMPLATE_OUTPUT_DIR` to publish them somewhere else.
- Task contracts can now also use `workflow_template=artifact_then_packs` plus `budget_policy_json.post_artifact_packs=[...]` to compose shared post-artifact planner branches (currently `dispatch` and `memory_candidate`) without adding another one-off named workflow template for every combination.
- The built-in `artifact_then_memory_candidate` workflow template now emits `step_input_prepare -> step_policy_evaluate -> step_artifact_save -> step_memory_candidate_stage`, persists the artifact, then stages a pending principal-scoped memory candidate through the same queue runtime so task contracts can write reviewable memory without adding a second API-side post-process.
- Task contracts can now also set `budget_policy_json.artifact_output_template=evidence_pack`, so `step_input_prepare` emits structured `claims`, `evidence_refs`, `open_questions`, and `confidence` fields that persist through `step_artifact_save` as a first-class evidence envelope and carry forward into downstream memory-candidate staging instead of only plain text.
- Those `evidence_pack` artifact saves now also materialize first-class evidence rows behind `/v1/evidence/objects`, carry stable `citation_handle` values plus `evidence_object_id` step-output metadata, and `POST /v1/evidence/merge` can recombine selected rows into a reusable evidence pack without reparsing the original artifact JSON.
- The built-in `artifact_then_dispatch_then_memory_candidate` workflow template now emits `step_input_prepare -> step_artifact_save -> step_policy_evaluate -> step_connector_dispatch -> step_memory_candidate_stage`, so approval-backed external sends can complete first and only then stage a pending memory candidate with delivery context from the finished workflow.
- That same `artifact_then_dispatch_then_memory_candidate` template can also combine with `budget_policy_json.human_review_role`, compiling `step_input_prepare -> step_human_review -> step_artifact_save -> step_policy_evaluate -> step_connector_dispatch -> step_memory_candidate_stage` so sensitive send workflows pause first for human review and still stage post-dispatch memory only after approval-backed delivery completes.
- That same `artifact_then_dispatch` template can also combine with `budget_policy_json.human_review_role`, compiling `step_input_prepare -> step_human_review -> step_artifact_save -> step_policy_evaluate -> step_connector_dispatch` so sensitive send flows pause first for human review, then later for approval-backed dispatch.
- That review-then-dispatch branch now also preserves compiled `dispatch_failure_strategy|dispatch_max_attempts|dispatch_retry_backoff_seconds` metadata on `step_connector_dispatch`, so an approval-resumed send step can requeue itself into the future and keep the session `queued` instead of surfacing a runtime error after human review has already cleared; the HTTP smoke path now proves that queued post-approval send contract as well.
- Unknown `budget_policy_json.workflow_template` values now fail fast with `422 unknown_workflow_template:<value>` during plan compilation and task execution, so contract mistakes stop at the boundary instead of silently falling back to the rewrite-shaped skeleton.
- That queued human-review step now also merges dependency outputs into the packet input, so `normalized_text`, `source_text`, and `text_length` follow the satisfied dependency graph instead of depending only on one parent link.
- Tool-call steps now flow through a registry-backed `ToolExecutionService`; the built-in `artifact_repository` handler emits normalized `tool.v1` receipt metadata, `tool_execution_completed` events, and self-heals its registry definition if the runtime starts with an empty built-in tool registry.
- `POST /v1/tools/execute` now exposes the same execution plane directly for built-in handlers; `connector.dispatch` self-heals its built-in registry definition the same way, queues a delivery outbox row, and returns normalized `tool.v1` receipt metadata.
- `connector.dispatch` execution now requires a real enabled connector binding in the caller's principal scope; foreign-principal or missing bindings fail before any outbox row is queued.
- `POST /v1/tools/execute` also exposes `browseract.extract_account_facts` and `browseract.extract_account_inventory`, which self-heal their built-in registry definitions, resolve BrowserAct-backed single-service or multi-service account facts from a principal-scoped connector binding, and can optionally call a live BrowserAct `run_url` with caller-supplied `instructions` / `account_hints_json` while projecting those live-discovery hints back through the structured output envelope for auditability.
- Human review/work packets can now be attached to a session with `POST /v1/human/tasks`, claimed by an operator, and returned with structured payload/provenance while emitting `human_task_created`, `human_task_claimed`, and `human_task_returned` ledger events.
- If `resume_session_on_return=true` is set on human task creation, the linked step reopens into `waiting_human`, the session becomes `awaiting_human`, and returning the packet resumes the step back to `completed`.
- Operator queue views can filter pending human tasks by `role_required`, `assigned_operator_id`, and `overdue_only=true` so reviewers can work from targeted SLA backlogs.
- Operator queue views can also pass `sort=created_asc` so the oldest-created backlog stays pinned first for manual FIFO triage, `sort=priority_desc_created_asc` so urgent and high work stays ahead of normal packets while each priority band remains FIFO, `sort=last_transition_desc` so the most recently reassigned, claimed, or returned ownership change surfaces first, `sort=sla_due_at_asc` so the earliest pending SLA surfaces first, or `sort=sla_due_at_asc_last_transition_desc` so same-SLA work stays ordered by the freshest ownership churn in general list and backlog views.
- Operator queue views can also pass `priority=urgent|high|normal|low` to isolate one priority band before applying any of the queue sort modes above.
- Operator queue views can also pass comma-separated filters like `priority=urgent,high` to pull a combined action queue without client-side set merging.
- Operator queue views can also pass `assignment_source=manual|recommended|auto_preselected` to open just one pending ownership slice instead of filtering manual or planner-preselected rows client-side after fetch.
- Manual and planner auto-preselected `priority-summary?assignment_source=...` slices are now also rechecked after extra ownerless rows are added, so mixed-source churn does not leak ownerless work into non-ownerless summary counts.
- `GET /v1/human/tasks/unassigned?assignment_source=none` isolates ownerless pending packets directly, so UIs do not need empty-string query conventions to open the unassigned-only backlog.
- `GET /v1/human/tasks/backlog?assignment_state=unassigned&assignment_source=none` exposes that same ownerless slice through the general pending backlog endpoint, so direct backlog and unassigned-only queues share one contract.
- `GET /v1/human/tasks/backlog?assignment_state=unassigned&assignment_source=none&sort=created_asc` keeps that ownerless slice in explicit FIFO order, so reviewer triage can pull oldest untouched ownerless work first.
- `GET /v1/human/tasks/backlog?assignment_state=unassigned&assignment_source=none&sort=last_transition_desc` now also proves the untouched ownerless slice sorts newest-first under freshest-ownership ordering, even when every row only has the initial `human_task_created` transition.
- `GET /v1/human/tasks/unassigned?assignment_source=none&sort=created_asc` now mirrors that FIFO ordering on the direct unassigned queue, so the dedicated ownerless view stays aligned with the backlog slice.
- `GET /v1/human/tasks/unassigned?assignment_source=none&sort=last_transition_desc` now mirrors that newest-first behavior on the direct unassigned queue, so the dedicated ownerless view and the general backlog stay aligned.
- `GET /v1/human/tasks?status=pending&assignment_state=unassigned&assignment_source=none&sort=created_asc` now mirrors that FIFO ordering on the general pending list too, keeping list, backlog, and unassigned ownerless triage on the same oldest-first contract.
- `GET /v1/human/tasks?status=pending&assignment_state=unassigned&assignment_source=none&sort=last_transition_desc` now mirrors that newest-first ordering on the general pending list too, so list, backlog, and unassigned ownerless triage all share the same freshest-transition contract.
- Those ownerless backlog, unassigned, and general pending `assignment_source=none` sorted queue slices are now also covered with manual and auto-preselected neighbors present, so mixed-source queues keep non-ownerless rows out of both `sort=created_asc` and `sort=last_transition_desc`.
- `GET /v1/human/tasks?session_id=<id>&assignment_source=none&sort=created_asc` now mirrors that FIFO ordering on the session-scoped ownerless slice too, so per-session triage stays aligned with the global queue views.
- `GET /v1/human/tasks?session_id=<id>&assignment_source=none&sort=last_transition_desc` now mirrors that newest-first ordering on the session-scoped ownerless slice too, so per-session triage shares the same freshest-transition contract as the global queue views.
- Those same session-scoped `assignment_source=none` sorted queue slices are now also covered with manual and auto-preselected neighbors present, so mixed-source sessions keep non-ownerless rows out of both `sort=created_asc` and `sort=last_transition_desc`.
- `GET /v1/rewrite/sessions/{session_id}?human_task_assignment_source=none` now also has explicit multi-task ownerless projection coverage, so the filtered `human_tasks` array and inline `human_task_assignment_history` both stay oldest-first for stable one-fetch session audit views.
- That filtered `human_task_assignment_source=none` session-detail projection is now also covered with manual and auto-preselected neighbors present, so mixed-source sessions keep current `human_tasks` ownerless-only while inline empty-source creation history stays oldest-first for one-fetch audit.
- That same mixed-source session-detail ownerless projection is now also count-checked, so the current `human_tasks` block stays at two ownerless rows while inline empty-source history still exposes a longer audit trail.
- `GET /v1/human/tasks?session_id=<id>&assignment_source=<source>` applies that same ownership-source filtering inside one session-scoped queue fetch, so operators can inspect only the manual or planner-preselected packets linked to a single execution thread.
- `GET /v1/human/tasks/priority-summary` returns queue counts per priority band (`urgent`, `high`, `normal`, `low`) plus `total` and `highest_priority`, so operators can choose the right priority filter before opening a backlog view.
- `GET /v1/human/tasks/priority-summary?assigned_operator_id=<id>` scopes those priority-band counts down to one assigned reviewer queue, so “mine” views can expose their own urgent/high load without fetching the full packet list first.
- `GET /v1/human/tasks/priority-summary?operator_id=<id>` scopes those priority-band counts down to only the exact backlog packets that match one operator profile’s role, rubric-derived skill tags, and trust tier, so pre-claim reviewer routing can size the candidate queue before anyone claims work.
- `GET /v1/human/tasks/priority-summary?assignment_source=manual|recommended|auto_preselected` scopes those priority-band counts down to one pending ownership source, so dashboards can distinguish planner-preselected packets from route-level recommended or manually assigned work before claim.
- `GET /v1/human/tasks/priority-summary?status=pending&assignment_state=unassigned&assignment_source=none` returns only ownerless pending counts, so the unassigned backlog can be sized without special empty-string filters.
- That same ownerless `priority-summary?status=pending&assignment_state=unassigned&assignment_source=none` slice is now also covered after mixed-source churn, so totals and low-priority counts stay ownerless-only even while manual and auto-preselected work coexists.
- The unsorted ownerless `assignment_source=none` list, backlog, and unassigned slices are now also covered after mixed-source churn, so multi-row queue fetches still contain only ownerless packets even while manual and auto-preselected work coexists.
- The unsorted session-scoped `session_id=<id>&assignment_source=none` slice is now also covered after mixed-source churn, so multi-row per-session queue fetches still contain only ownerless packets even while manual and auto-preselected work coexists.
- Both SLA-oriented queue sorts also fall back to oldest-created ordering for tasks without `sla_due_at`, so unscheduled pending work does not get reshuffled by ownership churn.
- `POST /v1/human/tasks/operators` now persists reviewer specialization profiles (`roles`, `skill_tags`, `trust_tier`), and `GET /v1/human/tasks/backlog?operator_id=<id>` filters pending work against that metadata plus human-task review contracts.
- Human task/session payloads now compute `routing_hints_json` from active operator profiles, rubric-derived skill tags, and trust-tier requirements, including `suggested_operator_ids`, `recommended_operator_id`, and `auto_assign_operator_id` when a single exact reviewer match is available.
- `GET /v1/human/tasks/backlog` is the direct pending-queue view, while `GET /v1/human/tasks/mine?operator_id=<id>` exposes the current operator assignment queue without rebuilding filters manually.
- `POST /v1/human/tasks/{human_task_id}/assign` sets `assigned_operator_id` while the task remains `pending`, emits `human_task_assigned`, and lets operators be pre-assigned before `claim` moves the packet into active work; if the caller omits `operator_id`, the route now uses `routing_hints_json.auto_assign_operator_id` when a single exact reviewer match is available.
- `GET /v1/human/tasks/{human_task_id}/assignment-history` filters the linked execution ledger down to `human_task_created`, `human_task_assigned`, `human_task_claimed`, and `human_task_returned` transitions so reassignment provenance is queryable without scanning the entire session event list, and those direct history rows now also carry originating `task_key`/`deliverable_type`.
- `GET /v1/human/tasks/{human_task_id}/assignment-history` also accepts `event_name`, `assigned_operator_id`, `assigned_by_actor_id`, and `assignment_source` to narrow that transition chain to specific reassignment, claim, return, recommended/manual/auto-preselected ownership views, or ownerless creation-only slices for operator tooling.
- `GET /v1/rewrite/sessions/{session_id}` now also includes `human_task_assignment_history`, mirroring those task-scoped ownership transitions inline with the broader session detail payload for one-fetch operator views, and inline assignment-history rows now also carry originating `task_key`/`deliverable_type`.
- `GET /v1/rewrite/sessions/{session_id}` inline `human_tasks` rows now also carry originating `task_key`/`deliverable_type`, so the paused packet detail itself stays self-describing for non-rewrite task contracts.
- Rewrite artifact reads, inline session artifact rows, and generic task execution responses now also expose explicit `principal_id` ownership alongside `mime_type`, `preview_text`, `storage_handle`, durable `body_ref`, and `structured_output_json` / `attachments_json`, so artifact consumers can start treating them as real metadata-plus-handle envelopes without dropping the current inline `content` contract.
- `GET /v1/rewrite/sessions/{session_id}?human_task_assignment_source=<source>` narrows the session-linked `human_tasks` array and inline `human_task_assignment_history` to one ownership source; `human_task_assignment_source=none` now exposes current ownerless packets plus empty-source creation history without special client-side handling.
- `GET /v1/human/tasks/unassigned` and `assignment_state=assigned|unassigned` make pre-assigned pending work distinct from ownerless pending work in the backlog view.
- Human task payloads now expose `assignment_state` directly (`unassigned`, `assigned`, `claimed`, `returned`) so session projections and operator queues do not have to infer assignment from `status` plus `assigned_operator_id`.
- Human task payloads now also persist `assignment_source` so operators can tell whether ownership came from a manual choice, a route-level recommended assignment, or planner-time auto-preselection even after later claim/return transitions.
- Human task payloads now also persist `assigned_at` and `assigned_by_actor_id` so current reviewer ownership is timestamped and the last assigning actor remains visible across assignment, claim, return, and planner auto-preselection.
- Human task list/detail/session rows now also expose compact `last_transition_event_name`, `last_transition_at`, `last_transition_assignment_state`, `last_transition_operator_id`, `last_transition_assignment_source`, and `last_transition_by_actor_id` fields so operators can see the most recent ownership event (`created`, `assigned`, `claimed`, or `returned`) plus its actor/source metadata without fetching the full assignment-history chain first.

## Operator Script Help Index

Use `--help` (or `-h`) on key scripts to print usage contracts quickly:

| Script | Help Command | Purpose |
|---|---|---|
| `scripts/deploy.sh` | `bash scripts/deploy.sh --help` | Deploy runtime (standard or memory-only) |
| `scripts/db_bootstrap.sh` | `bash scripts/db_bootstrap.sh --help` | Apply kernel DB migrations |
| `scripts/db_status.sh` | `bash scripts/db_status.sh --help` | Check kernel table presence/counts |
| `scripts/db_size.sh` | `bash scripts/db_size.sh --help` | Inspect table/index/total DB size footprint |
| `scripts/db_retention.sh` | `bash scripts/db_retention.sh --help` | Dry-run/apply runtime retention pruning |
| `scripts/smoke_api.sh` | `bash scripts/smoke_api.sh --help` | Run API smoke contracts |
| `scripts/smoke_help.sh` | `bash scripts/smoke_help.sh --help` | Verify `--help` usage contracts for operator scripts |
| `scripts/smoke_postgres.sh` | `bash scripts/smoke_postgres.sh --help` | Run end-to-end Postgres-backed smoke contract |
| `scripts/test_postgres_contracts.sh` | `bash scripts/test_postgres_contracts.sh --help` | Run isolated Postgres-backed repository contract tests |
| `scripts/hard_exit_gates.sh` | `bash scripts/hard_exit_gates.sh --help` | Run the full flagship hard-exit bundle |
| `scripts/runtime_hard_exit_gates.sh` | `bash scripts/runtime_hard_exit_gates.sh --help` | Run the deploy-safe runtime hard-exit bundle |
| `scripts/verify_ltd_critical_entries.py` | `python3 scripts/verify_ltd_critical_entries.py --help` | Fail closed on runtime-critical LTD drift |
| `scripts/verify_ltd_flagship_subset.py` | `python3 scripts/verify_ltd_flagship_subset.py --help` | Fail closed on the named flagship LTD subset |
| `scripts/list_endpoints.sh` | `bash scripts/list_endpoints.sh --help` | Print live endpoint inventory from OpenAPI |
| `scripts/version_info.sh` | `bash scripts/version_info.sh --help` | Print git and milestone/version fingerprint |
| `scripts/export_openapi.sh` | `bash scripts/export_openapi.sh --help` | Export timestamped OpenAPI snapshot |
| `scripts/diff_openapi.sh` | `bash scripts/diff_openapi.sh --help` | Diff OpenAPI snapshots |
| `scripts/prune_openapi.sh` | `bash scripts/prune_openapi.sh --help` | Prune old OpenAPI snapshots |
| `scripts/operator_summary.sh` | `bash scripts/operator_summary.sh --help` | Print compact operator command inventory |
| `scripts/support_bundle.sh` | `bash scripts/support_bundle.sh --help` | Build operator support bundle |
| `scripts/archive_tasks.sh` | `bash scripts/archive_tasks.sh --help` | Archive/prune local task log Done rows |
| `scripts/bootstrap_payfunnels_propertyquarry.py` | `python3 scripts/bootstrap_payfunnels_propertyquarry.py --help` | Prepare PayFunnels webhook/runtime config for PropertyQuarry |
| `scripts/bootstrap_emailit_propertyquarry.py` | `python3 scripts/bootstrap_emailit_propertyquarry.py --help` | Prepare and inspect the PropertyQuarry Emailit sending domain |
| `scripts/verify_release_assets.sh` | `bash scripts/verify_release_assets.sh --help` | Verify release artifact completeness |

Combined index:

```bash
make operator-help
```

`bash scripts/version_info.sh` still prints milestone capability-status counts and release tags from `MILESTONE.json` as delivery history, but EA flagship release claims now come from `EA_FLAGSHIP_TRUTH_PLANE.md`, `EA_FLAGSHIP_RELEASE_GATE.json`, and `EA_FLAGSHIP_RELEASE_GATE.generated.json`.
Refresh the machine-readable receipt with `python3 scripts/materialize_ea_flagship_release_gate.py`.
Refresh the weekly pulse in `WEEKLY_PRODUCT_PULSE.generated.json` with `python3 scripts/materialize_weekly_product_pulse.py`.
EA product canon for those claims now lives in `.codex-design/ea/START_HERE.md`.

## Local Gate Summary

The local release-check bundle is:

- `make smoke-help`
- `make ci-local`
- `make test-api`
- `make materialize-release-assets`
- `make verify-release-assets`
- `make materialize-deploy-context`
- `make materialize-release-manifest`
- `make verify-deploy-context`
- `make verify-release-authority`
- `make verify-release-authority-runtime`
- `make verify-release-authority-runtime-authoritative`
- `make release-authority-probe`
- `make verify-flagship-release-readiness`
- `make verify-whole-project-gold-map`
- `make verify-generated-release-artifacts-clean`
- `make runtime-hard-exit-gates`
- `make hard-exit-gates`
- `bash scripts/smoke_postgres.sh`
- `bash scripts/test_postgres_contracts.sh`
- `bash scripts/smoke_postgres.sh --legacy-fixture`

Release-preflight highlights:

  - `make materialize-release-assets`
  - `make verify-release-authority`
  - `make release-authority-probe`
  - `make verify-flagship-release-readiness`
  - `make verify-whole-project-gold-map`
  - `make verify-generated-release-artifacts-clean`

Milestone tracking linkage remains historical, but EA flagship release claims now key off `EA_FLAGSHIP_TRUTH_PLANE.md`, `EA_FLAGSHIP_RELEASE_GATE.json`, and the generated receipt instead of treating `MILESTONE.json` as the oracle.

Local mirror command:

```bash
make ci-gates
```

Local mirror including Postgres smoke:

```bash
make ci-gates-postgres
```

Aggregate LTD release verification:

```bash
make ltd-release-gates
```

Isolated Postgres repository-contract run:

```bash
make test-postgres-contracts
```

Current `scripts/test_postgres_contracts.sh` coverage includes artifacts, channel runtime, approvals, policy decisions, and task contracts.
The principal-scoped memory seed APIs are covered in-process by `tests/smoke_runtime_api.py` and over HTTP by the approved `scripts/smoke_api.sh` path that `scripts/smoke_postgres.sh` invokes. That Postgres smoke script now also force-recreates `ea-api` on rebuild so host smoke validates the current container image instead of a stale running process.

Local mirror including legacy migration-regression smoke:

```bash
make ci-gates-postgres-legacy
```

Release ops linkage: `RELEASE_CHECKLIST.md` includes `make ci-gates` and `make ci-gates-postgres-legacy` as optional local parity commands.

## 1) Start Services

```bash
bash scripts/deploy.sh
# or
make deploy-ea-prod
```

`make deploy` refuses ambiguous deployment. Use `make deploy-ea-prod` for EA services or `make deploy-property` when you intentionally want the PropertyQuarry stack.

Memory-only local mode (API without DB dependency):

```bash
EA_MEMORY_ONLY=1 bash scripts/deploy.sh
# or
make deploy-memory
```

With schema bootstrap in one step:

```bash
EA_BOOTSTRAP_DB=1 bash scripts/deploy.sh
# or
make deploy-bootstrap
```

## 2) Apply Kernel Migrations Manually

```bash
bash scripts/db_bootstrap.sh
# or
make bootstrap
```

Applies:
- `ea/schema/20260305_v0_2_execution_ledger_kernel.sql`
- `ea/schema/20260305_v0_3_channel_runtime_kernel.sql`
- `ea/schema/20260305_v0_4_policy_decisions_kernel.sql`
- `ea/schema/20260305_v0_5_artifacts_kernel.sql`
- `ea/schema/20260305_v0_6_execution_ledger_v2.sql`
- `ea/schema/20260305_v0_7_approvals_kernel.sql`
- `ea/schema/20260305_v0_8_channel_runtime_reliability.sql`
- `ea/schema/20260305_v0_9_tool_connector_kernel.sql`
- `ea/schema/20260305_v0_10_task_contracts_kernel.sql`
- `ea/schema/20260305_v0_11_memory_kernel.sql`
- `ea/schema/20260305_v0_12_entities_relationships_kernel.sql`
- `ea/schema/20260305_v0_13_commitments_kernel.sql`
- `ea/schema/20260305_v0_14_authority_bindings_kernel.sql`
- `ea/schema/20260305_v0_15_delivery_preferences_kernel.sql`
- `ea/schema/20260305_v0_16_follow_ups_kernel.sql`
- `ea/schema/20260305_v0_17_deadline_windows_kernel.sql`
- `ea/schema/20260305_v0_18_stakeholders_kernel.sql`
- `ea/schema/20260305_v0_19_decision_windows_kernel.sql`
- `ea/schema/20260305_v0_20_communication_policies_kernel.sql`
- `ea/schema/20260305_v0_21_follow_up_rules_kernel.sql`
- `ea/schema/20260305_v0_22_interruption_budgets_kernel.sql`
- `ea/schema/20260305_v0_23_execution_queue_kernel.sql`
- `ea/schema/20260305_v0_24_human_tasks_kernel.sql`
- `ea/schema/20260305_v0_25_human_task_resume_kernel.sql`
- `ea/schema/20260305_v0_26_human_task_assignment_state.sql`
- `ea/schema/20260305_v0_27_human_task_review_contract.sql`
- `ea/schema/20260305_v0_28_operator_profiles_kernel.sql`
- `ea/schema/20260305_v0_29_human_task_assignment_source.sql`
- `ea/schema/20260305_v0_30_human_task_assignment_provenance.sql`

Check table presence/counts:

```bash
bash scripts/db_status.sh
# or
make db-status
```

Check table/index size footprint:

```bash
bash scripts/db_size.sh
# or
make db-size

# optional table-prefix filter
EA_DB_SIZE_TABLE_PREFIX=execution_ bash scripts/db_size.sh

# optional schema filter
EA_DB_SIZE_SCHEMA=public bash scripts/db_size.sh

# optional sort key (total|table|index)
EA_DB_SIZE_SORT_KEY=index bash scripts/db_size.sh

# optional minimum table size filter (MB)
EA_DB_SIZE_MIN_MB=25 bash scripts/db_size.sh
```

The Compose Postgres volume is `ea_pgdata`, mounted at `/var/lib/postgresql/data` inside `ea-db`.
If `/var/lib/docker/volumes/.../ea_pgdata` is large on the host, that is on-disk Postgres runtime state
(ledger, outbox, observations, memory tables, indexes), not RAM. Use `bash scripts/db_size.sh`
to attribute the footprint by table/index size before pruning or moving data.
`bash scripts/support_bundle.sh` now captures the expected volume name/mount and live `ea-db` mount inspection
by default, so support bundles can answer which host path backs `/var/lib/postgresql/data`.

Retention dry-run (default) and apply mode:

```bash
bash scripts/db_retention.sh
# or
make db-retention

# optional retention profile
EA_RETENTION_PROFILE=aggressive bash scripts/db_retention.sh

# optional per-table override
EA_RETENTION_DELIVERY_SENT_DAYS=14 bash scripts/db_retention.sh

# optional table allowlist (CSV)
EA_RETENTION_TABLES=execution_events,delivery_outbox bash scripts/db_retention.sh

# optional table skip list (CSV)
EA_RETENTION_SKIP_TABLES=observation_events,policy_decisions bash scripts/db_retention.sh

# apply deletions
bash scripts/db_retention.sh --apply
```

## 3) Health Check

```bash
curl -fsS http://localhost:${EA_HOST_PORT:-8090}/health
curl -fsS http://localhost:${EA_HOST_PORT:-8090}/health/live
curl -fsS http://localhost:${EA_HOST_PORT:-8090}/health/ready
curl -fsS http://localhost:${EA_HOST_PORT:-8090}/version
curl -fsS http://localhost:${EA_HOST_PORT:-8090}/health/release-authority
```

## 4) Rewrite + Session Audit Smoke

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/artifact \
  -H 'content-type: application/json' \
  -d '{"text":"runbook smoke"}'
```

Use returned `artifact_id` and `execution_session_id`:

```bash
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/artifacts/<artifact_id>"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/receipts/<receipt_id>"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/run-costs/<cost_id>"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/sessions/<session_id>"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/policy/decisions/recent?session_id=<session_id>&limit=5"
```

External-send policy preview:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/policy/evaluate \
  -H 'content-type: application/json' \
  -d '{"content":"Send the board update to the distribution list.","tool_name":"connector.dispatch","action_kind":"delivery.send","channel":"email"}'
```

## 5) Observation + Delivery Smoke

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/observations/ingest \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","channel":"email","event_type":"thread.opened","payload":{"subject":"Board prep"}}'
```

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/delivery/outbox \
  -H 'content-type: application/json' \
  -d '{"channel":"slack","recipient":"U1","content":"Draft ready","metadata":{"priority":"high"}}'
```

```bash
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/observations/recent?limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/delivery/outbox/pending?limit=10"
```

## 6) Telegram Adapter Smoke

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/channels/telegram/ingest \
  -H 'content-type: application/json' \
  -d '{"update":{"message":{"chat":{"id":42},"text":"hello","message_id":7,"date":123}}}'
```

## 7) Full Smoke Script

```bash
bash scripts/smoke_api.sh
# or
make smoke-api
# or (includes help-smoke + API smoke)
make release-smoke
# postgres-backed smoke path
bash scripts/smoke_postgres.sh
# or
make smoke-postgres
# optional isolated DB name override
EA_SMOKE_DB=ea_smoke_runtime bash scripts/smoke_postgres.sh
# legacy migration-regression mode (skips API smoke)
bash scripts/smoke_postgres.sh --legacy-fixture
# or
make smoke-postgres-legacy
```

The smoke script now includes external-send policy evaluation plus a blocked-policy assertion (`403` on oversized rewrite input) and runs against an isolated smoke DB so legacy runtime data is not mutated.

## 8) Memory Candidate Promotion Smoke

For every principal-scoped connector or memory example below, send `X-EA-Principal-ID: principal-default` (or your chosen principal). If you also pass `principal_id`, it must match that request header or the runtime will return `403 principal_scope_mismatch`.

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/candidates \
  -H "X-EA-Principal-ID: principal-default" \
  -H 'content-type: application/json' \
  -d '{"category":"stakeholder_pref","summary":"CEO prefers concise updates","fact_json":{"tone":"concise"}}'
```

Promote using the returned `candidate_id`:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/candidates/<candidate_id>/promote \
  -H "X-EA-Principal-ID: principal-default" \
  -H 'content-type: application/json' \
  -d '{"reviewer":"operator","sharing_policy":"private"}'
curl -fsS -H "X-EA-Principal-ID: principal-default" "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/items?limit=10"
```

Seed semantic entities/relationships:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/entities \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","entity_type":"person","canonical_name":"Alex Executive","attributes_json":{"role":"executive"}}'
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/relationships \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","from_entity_id":"<entity_a>","to_entity_id":"<entity_b>","relationship_type":"reports_to"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/entities?limit=10&principal_id=principal-default"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/relationships?limit=10&principal_id=principal-default"
```

Principal-scoped commitments:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/commitments \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","title":"Send board follow-up","details":"Draft by Friday","status":"open","priority":"high"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/commitments?principal_id=principal-default&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/commitments/<commitment_id>?principal_id=principal-default"
```

Principal-scoped authority bindings:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/authority-bindings \
  -H "X-EA-Principal-ID: principal-default" \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","subject_ref":"assistant","action_scope":"calendar.write","approval_level":"manager","channel_scope":["email","slack"],"policy_json":{"quiet_hours_enforced":true},"status":"active"}'
curl -fsS -H "X-EA-Principal-ID: principal-default" "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/authority-bindings?principal_id=principal-default&limit=10"
curl -fsS -H "X-EA-Principal-ID: principal-default" "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/authority-bindings/<binding_id>?principal_id=principal-default"
```

If the request principal and a supplied `principal_id` disagree, the runtime now returns `403 principal_scope_mismatch` instead of silently reading another principal scope.

Principal-scoped delivery preferences:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/delivery-preferences \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","channel":"email","recipient_ref":"ceo@example.com","cadence":"urgent_only","quiet_hours_json":{"start":"22:00","end":"07:00"},"format_json":{"style":"concise"},"status":"active"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/delivery-preferences?principal_id=principal-default&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/delivery-preferences/<preference_id>?principal_id=principal-default"
```

Principal-scoped follow-ups:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-ups \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","stakeholder_ref":"ceo@example.com","topic":"Board follow-up","status":"open","due_at":"2026-03-07T09:00:00+00:00","channel_hint":"email","notes":"Send summary after prep call","source_json":{"source":"manual"}}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-ups?principal_id=principal-default&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-ups/<follow_up_id>?principal_id=principal-default"
```

Principal-scoped deadline windows:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/deadline-windows \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","title":"Board prep delivery window","start_at":"2026-03-07T08:30:00+00:00","end_at":"2026-03-07T10:00:00+00:00","status":"open","priority":"high","notes":"Draft must be ready before board sync","source_json":{"source":"manual"}}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/deadline-windows?principal_id=principal-default&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/deadline-windows/<window_id>?principal_id=principal-default"
```

Principal-scoped stakeholders:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/stakeholders \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","display_name":"Sam Stakeholder","channel_ref":"email:sam@example.com","authority_level":"approver","importance":"high","response_cadence":"fast","tone_pref":"diplomatic","sensitivity":"confidential","escalation_policy":"notify_exec","open_loops_json":{"board_follow_up":"open"},"friction_points_json":{"scheduling":"tight"},"last_interaction_at":"2026-03-06T15:30:00+00:00","status":"active","notes":"Needs concise summaries"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/stakeholders?principal_id=principal-default&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/stakeholders/<stakeholder_id>?principal_id=principal-default"
```

Principal-scoped decision windows:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/decision-windows \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","title":"Board response decision","context":"Choose timing and channel for reply","opens_at":"2026-03-06T08:00:00+00:00","closes_at":"2026-03-06T12:00:00+00:00","urgency":"high","authority_required":"exec","status":"open","notes":"Needs decision before board prep","source_json":{"source":"manual"}}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/decision-windows?principal_id=principal-default&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/decision-windows/<decision_window_id>?principal_id=principal-default"
```

Principal-scoped communication policies:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/communication-policies \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","scope":"board_threads","preferred_channel":"email","tone":"concise_diplomatic","max_length":1200,"quiet_hours_json":{"start":"22:00","end":"07:00"},"escalation_json":{"on_high_urgency":"notify_exec"},"status":"active","notes":"Board-facing communication defaults"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/communication-policies?principal_id=principal-default&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/communication-policies/<policy_id>?principal_id=principal-default"
```

Principal-scoped follow-up rules:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-up-rules \
  -H 'content-type: application/json' \
  -d '{"principal_id":"principal-default","name":"Board reminder escalation","trigger_kind":"deadline_risk","channel_scope":["email","slack"],"delay_minutes":120,"max_attempts":3,"escalation_policy":"notify_exec","conditions_json":{"priority":"high"},"action_json":{"action":"draft_follow_up"},"status":"active","notes":"Escalate if follow-up is late"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-up-rules?principal_id=principal-default&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-up-rules/<rule_id>?principal_id=principal-default"
```
## 9) Script Help Smoke

```bash
bash scripts/smoke_help.sh
# or
make smoke-help
```

## 10) Export OpenAPI Snapshot

```bash
bash scripts/export_openapi.sh
# or
make openapi-export
```

Compare the latest two snapshots:

```bash
bash scripts/diff_openapi.sh
# or
make openapi-diff
```

Prune old snapshots (default keep=20):

```bash
bash scripts/prune_openapi.sh
# keep 50
bash scripts/prune_openapi.sh 50
# or
make openapi-prune
```

## 11) Optional Local Pre-Commit Hook

```bash
mkdir -p .githooks
cp .githooks/pre-commit.example .githooks/pre-commit
chmod +x .githooks/pre-commit
git config core.hooksPath .githooks
```

## 12) Print Endpoint Inventory

```bash
bash scripts/list_endpoints.sh
# or
make endpoints
```

## 13) Print Version Fingerprint

```bash
bash scripts/version_info.sh
# or
make version-info
```

## 14) Print Operator Summary

```bash
bash scripts/operator_summary.sh
# or
make operator-summary
```

The operator summary includes release smoke/readiness commands plus legacy smoke/parity shortcuts, release/support commands such as `make release-preflight` and `make support-bundle`, and task-archive shortcuts.
It also includes the aggregate LTD release gate shortcut `make ltd-release-gates`.
It also includes `make probe-operator-readiness` as the aggregate live-ops triage entrypoint across Telegram, WhatsApp, My Media for Alexa, Teable recovery, and proactive OODA route/artifact posture. The aggregate JSON contract is scrubbed before it leaves the probe: raw operator principal ids, binding ids, session refs, loopback pairing URLs, QR file paths, and Pushbullet client suffixes are converted into presence booleans, public EA surfaces, or redacted host-local labels so dashboards and receipts stay actionable without exposing host-only handles. When a Sonarr season target is configured through `EA_OPERATOR_READINESS_SONARR_SERIES_ID` or `EA_OPERATOR_READINESS_SONARR_SERIES_TITLE` plus `EA_OPERATOR_READINESS_SONARR_SEASON_NUMBER`, that same aggregate also adds a `sonarr_tv_season` component so import drift, missing monitored episodes, and stale metadata-only queue rows show up in the top-level operator queue; you can also inject the target ad hoc with `make probe-operator-readiness SONARR_SERIES_ID=36 SONARR_SEASON_NUMBER=2`. When My Media already has a resumable Amazon waiting-code or consent handoff, that aggregate probe appends a dry-run `mymedia_pairing_telegram` component so the operator can see whether the Telegram nudge lane is actually ready without sending a live message. Use `scripts/ea_live_ops.py probe-operator-readiness --no-pairing --format operator` when you want passive triage only; it suppresses QR recovery and My Media pairing handoff subprobes while keeping the base WhatsApp/My Media status components. `make materialize-ea-operator-readiness` publishes that same aggregate into `.codex-studio/published/ea_operator_readiness.generated.json` with passive pairing mode by default so scheduled or dashboard receipts do not create QR or pairing handoff artifacts, and it accepts the same optional `SONARR_SERIES_ID|SONARR_SERIES_TITLE` plus `SONARR_SEASON_NUMBER` overrides when the published receipt should cover the TV-import lane too. `make verify-ea-operator-readiness` proves the published receipt still matches current source state. The standalone WhatsApp runtime gate `make verify-whatsapp-web-action-processor-readiness` still proves action-processor health without overclaiming live audiobook delivery. When the gate reports `sidecar_not_ready` with QR required, run `make probe-whatsapp-pairing` to materialize the current QR SVG under ignored `.runtime/whatsapp-pairing/`; run `make send-whatsapp-pairing-telegram` only when you want to send that QR document to the configured Telegram operator route. Telegram captions deliberately omit host-local `127.0.0.1` pairing URLs, because those only work from the EA host; the attached QR is the recipient action. After publication, `make verify-whatsapp-audiobook-public-share-playback` replays the shared player route in Playwright and proves the audio actually advances.
Inside that same `-- goal posture --` block, the operator summary now mirrors the detect-lens aggregate as `operator triage`, `operator focus`, and `operator next` so the compact summary shows the current no-secret live-ops blockers and the next operator step alongside `detect`, `decide`, `deliver`, `recover`, and `prove`.
For the Google Workspace OAuth lane, `scripts/ea_live_ops.py probe-google-workspace-oauth --expected-google-email work.tibor.girschele@gmail.com --format operator` or `make probe-google-workspace-oauth EXPECTED_GOOGLE_EMAIL=work.tibor.girschele@gmail.com` now reuses the current published OAuth receipt context when you omit fresh observed-error or observed-account hints. That keeps the direct probe aligned with the last real retry/setup blocker instead of downgrading it to a generic manual-console status. The aggregate `make probe-operator-readiness` lane no longer replays that last blocker when the runtime is missing `EA_GOOGLE_WORKSPACE_EXPECTED_EMAIL` or `EA_GOOGLE_OAUTH_EXPECTED_EMAIL`; it reports `expected_google_email_missing` as the current blocker and keeps the last published receipt status/age only as operator context.
For provider-specific live checks, use the shared provider probe instead of bespoke wrappers: `scripts/ea_live_ops.py probe-provider --provider pushbullet --format operator` or `make probe-live-provider PROVIDER=pushbullet` surfaces the no-secret Pushbullet readiness lane, and the same entrypoint works for `PROVIDER=onemin`, `PROVIDER=unmixr`, or other registered provider keys. The default provider order remains fast/cheap first: 1min is the primary low-cost lane, with Magicx and the governed fallback order used only when current runtime health permits. When Pushbullet uses a named fallback route instead of literal default envs, the operator probe now shows that effective route as a no-secret `account=` label such as `default->elisabeth`, so default-route drift is visible without exposing emails or tokens. When the Pushbullet relay is enabled, that alias still does not count as a second account: the readiness receipt stays blocked until the relay primary and secondary client keys resolve to two distinct live Pushbullet accounts. When you need the published no-secret Pushbullet readiness receipt instead of a transient operator line, run `python3 scripts/materialize_pushbullet_delivery_readiness.py --pretty` and `python3 scripts/verify_pushbullet_delivery_readiness.py --pretty`. When the question is burn/cooldown posture rather than plain readiness, use `scripts/ea_live_ops.py probe-provider-cost-pressure --window 24h --format operator` or `make probe-live-provider-cost-pressure WINDOW=24h`; add `PRINCIPAL_ID=...` only when you need a non-default principal lens.
For Teable recovery drift, `make probe-teable-recovery` now surfaces sample `different_hash_key_samples` when the table and local runtime disagree only on current env values. Treat those samples as the review list: if the local change is intentional, refresh the backup after review; if it is accidental, recover from Teable instead of papering over the count. The probe still keeps secret values out of the receipt and exposes only env-key or file-path identifiers.
Use `make probe-mymedia-alexa` when the Alexa media stack looks half-configured: it checks the live container, redacted Amazon pairing state, watch-folder/index counters, and external-access posture without printing refresh tokens, paired-user identifiers, watch paths, or the configured public IP. If `EA_MYMEDIA_ALEXA_PUBLIC_BASE_URL` is set, the same probe also classifies the public admin surface without leaking raw redirect URLs, cookies, headers, or challenge bodies: `access_protected` means Cloudflare Access is fronting the console, `reachable` means the public URL answered directly, `route_not_found` means the hostname/tunnel path still falls through, and `blocked_by_cloudflare` means the edge is serving a block page instead of the My Media console. `make materialize-mymedia-alexa-readiness` writes the no-secret published receipt and `make verify-mymedia-alexa-readiness` proves it still matches current source state; the receipt also carries a dry-run `pairing_telegram_delivery` block so operator transport readiness for the saved-session-first Telegram handoff is captured without sending a live message during normal proof refresh. That published block now re-sanitizes nested Telegram payloads too: raw operator principal ids, binding ids, message ids, and loopback `127.0.0.1` action URLs are replaced with presence flags or host-local/public-safe surfaces before they reach the published receipt. When the local probe reports `status=blocked_console_unreachable`, run `make repair-mymedia-console-api`; the live-ops repair command restarts the current My Media container, waits for the local JSON console API to answer again, writes a local receipt under `.state/mymedia-alexa/console-api-repair.receipt.json`, and then re-probes before the follow-up readiness receipt is published. When the public console lands in `route_not_found` or `blocked_by_cloudflare`, run `make repair-mymedia-public-surface`; the live-ops repair command rechecks the public URL, repairs the matching Cloudflare DNS/tunnel/Access posture against the current `EA_MYMEDIA_ALEXA_PUBLIC_BASE_URL`, writes a local receipt under `.state/mymedia-alexa/public-console-repair.receipt.json`, and then re-probes before the follow-up readiness receipt is published. Route-specific private defaults that should not sit in committed env files now belong in ignored `.state/mymedia-alexa/runtime-defaults.json` or a custom `EA_MYMEDIA_ALEXA_RUNTIME_DEFAULTS_PATH`; supported keys are `amazon_otp_channel`, `amazon_phone_suffix`, `access_emails`, and `cloudflare_exception_base_hosts`, and any explicit env vars still override that file. If the probe reports `status=blocked_pairing_required`, first look at `next=`: `next=enter_mymedia_amazon_pairing_code` means a fresh private handoff already exists under `.runtime/mymedia-amazon-pairing/` and you should resume it with `make submit-mymedia-amazon-pairing-code OTP_CODE=...`; otherwise run `make trigger-mymedia-amazon-pairing` to drive the actual My Media setup wizard to the Amazon MFA boundary and store a fresh resume bundle. `make send-mymedia-amazon-pairing-telegram` now reuses a fresh saved handoff before it retriggers the browser flow, and it can nudge either the waiting-for-code step or the pending Amazon consent step over Telegram without exposing the saved resume URL. If a later route experiment only produces an Amazon cooldown or a dead OTP route, the runtime keeps the last fresh waiting-code or consent handoff intact so the operator can still resume the valid bundle. Once the probe sees the Amazon account paired again, it automatically removes the obsolete `.runtime/mymedia-amazon-pairing/` bundle so browser-state secrets and screenshots do not linger after recovery. Treat queued or empty library counters as expected until the pairing completes; when the probe reports `status=blocked_library_scan_pending`, pairing is already present and the next action is a real library rescan or watch-folder repair. Run `make rescan-mymedia-library` to hit the local My Media console `POST /api/Rescan` endpoint through EA’s no-secret live-ops wrapper; if the request is accepted, the follow-up receipt switches to `next=wait_for_mymedia_library_scan` so the operator knows the command worked and the remaining step is waiting rather than retrying blindly. Once tracks are already appearing, the base `make probe-mymedia-alexa` probe upgrades to `status=ready_library_scan_in_progress` and keeps `next=wait_for_mymedia_library_scan`, so active indexing stops counting as a blocker while still exposing the remaining wait.
Use `make probe-sonarr-tv-season SONARR_SERIES_ID=36 SONARR_SEASON_NUMBER=2` when a TV season looks incomplete in Sonarr even though the downloader or staging disk already has files. The probe reads the live Sonarr API key from the configured `EA_SONARR_CONFIG_PATH`, inspects the target series/season through Sonarr, classifies missing monitored episodes, unreadable on-disk episode files, Sonarr episode-file rows still missing media-info, metadata-only queue rows, stale metadata queue age, and staging-pack recovery candidates under the configured `EA_SONARR_STAGING_ROOT`, and returns only operator-safe fields. When local `ffprobe` is available, “has file” is verified against the actual video payload so zero-filled or otherwise unreadable files do not get silently treated as healthy, and staged single-episode files are only treated as actionable imports when their own media payload probes cleanly. If the numeric id is unknown, use `SONARR_SERIES_TITLE='LEGO Ninjago: Dragons Rising'` instead of `SONARR_SERIES_ID`; the title resolver stays local to Sonarr and does not invent EA-side catalog truth.
When the probe reports missing or unreadable episodes, run `make repair-sonarr-tv-season SONARR_SERIES_ID=36 SONARR_SEASON_NUMBER=2`. That repair path is intentionally narrow and idempotent: it imports from any validated matching staged candidates in one pass, quarantines unreadable library files into a hidden sibling `.ea-sonarr-quarantine/` directory on the same media filesystem, requests `RefreshSeries` plus `RescanSeries`, removes only stale metadata-only queue rows with `removeFromClient=true`, and if real missing episodes remain it requests a Sonarr `EpisodeSearch` for those episode ids before writing the private receipt under `.state/sonarr-tv/series-<id>-season-<nn>.repair.receipt.json`. Fresh metadata-only queue rows now downgrade to a wait/reprobe recovery action instead of immediately telling the operator to rerun repair, while stale rows still point back to the cleanup lane. Use it for import/corruption/queue cleanup; if the probe shows no validated staged pack and the follow-up search still cannot acquire the episodes, the remaining gap is a true acquisition problem rather than hidden library drift.
It also prints the current long-running goal posture through `detect`, `decide`, `deliver`, `recover`, and `prove`, keeping local receipt evidence separate from command-backed recovery checks and real-world acceptance blockers.
Materialize or verify that posture directly with `make materialize-continuous-improvement-goal-posture` and `make verify-continuous-improvement-goal-posture`.

When `make materialize-proactive-ooda-operator-status` or `make verify-proactive-ooda-operator-status` reports `reason=browser_handoff_required`, treat that as a live browser challenge rather than a queue-quality failure. The receipt mirrors a redacted `browser_handoff` contract with the blocker code, site host, masked destination hint, challenge channels, and operator instruction. Use the surfaced queue link, complete the live challenge in the preserved browser session, then rerun the operator-status materializer or verifier to confirm the handoff cleared. Raw phone numbers, email addresses, cookies, and credentials must not appear in that receipt.

## 15) Generate Support Bundle

```bash
bash scripts/support_bundle.sh
# optional log tail length
SUPPORT_LOG_TAIL_LINES=500 bash scripts/support_bundle.sh
# optional: skip DB logs
SUPPORT_INCLUDE_DB=0 bash scripts/support_bundle.sh
# optional: skip API logs
SUPPORT_INCLUDE_API=0 bash scripts/support_bundle.sh
# optional: skip DB volume attribution
SUPPORT_INCLUDE_DB_VOLUME=0 bash scripts/support_bundle.sh
# optional: skip DB size snapshot
SUPPORT_INCLUDE_DB_SIZE=0 bash scripts/support_bundle.sh
# optional: DB size snapshot top-table limit
SUPPORT_DB_SIZE_LIMIT=15 bash scripts/support_bundle.sh
# inspect the same clean-receipt blocker groups without writing a bundle
make inspect-source-dirty-groups
# verify the grouping report contract before handing the blocker off
make verify-source-dirty-groups
# support bundles include both ea.source_dirty_groups.v1 and ea.source_dirty_groups_verifier.v1
# list group names/counts before drilling into one blocker group
scripts/inspect_source_dirty_groups.py --list-categories
# narrow the source-dirty view to one blocker group
scripts/inspect_source_dirty_groups.py --category api_routes --limit 20
# optional: skip queue snapshot
SUPPORT_INCLUDE_QUEUE=0 bash scripts/support_bundle.sh
# optional: custom filename prefix
SUPPORT_BUNDLE_PREFIX=incident_42 bash scripts/support_bundle.sh
# optional: custom timestamp format
SUPPORT_BUNDLE_TIMESTAMP_FMT=%Y-%m-%dT%H%M%SZ bash scripts/support_bundle.sh
# or
make support-bundle
```

`support_bundle.sh` applies baseline redaction patterns for common secret/token/password forms.

## 16) Archive Completed Task Rows

```bash
# append Done rows to TASKS_ARCHIVE.md
bash scripts/archive_tasks.sh
# preview archive rows only
bash scripts/archive_tasks.sh --dry-run
# append + prune Done rows in the local TASKS_WORK_LOG.md
bash scripts/archive_tasks.sh --prune-done
# or
make tasks-archive
make tasks-archive-dry-run
make tasks-archive-prune
```

## 17) Verify Release Assets

```bash
bash scripts/verify_release_assets.sh
# or
make verify-release-assets
make verify-whole-project-gold-map
make verify-memorial-runtime-overlay
make verify-memorial-voice-stability
make materialize-memorial-phrase-bank
make materialize-memorial-operator-status
make materialize-memorial-room-audio-gold-clean
# docs-focused alias
make docs-verify
# docs + operator-help bundle
make release-docs
```

Use `make release-docs` as a pre-smoke documentation/usage pass before running `make release-preflight`. `make verify-runtime-supply-chain` is the runtime dependency and pinned-image guard for release-stage claims. `make verify-release-authority` is the deploy-truth guard: it fails closed unless the manifest records a runtime public origin, explicit deployment id, clean worktree, and compose topology strong enough for a shipping claim. `make materialize-deploy-context` is the deploy-attempt receipt: it must carry repository, branch, tracking branch, commit, deployment id, public origin, release label, project mode, and compose topology before the release manifest can claim authority. `make verify-release-authority-runtime-authoritative` is the live-runtime guard: it fails unless the running `/health/release-authority` surface is internally consistent, `clear`, `authoritative_runtime`, and both nested release/deploy gates pass. `make verify-whole-project-gold-map` is the explicit overclaim guard: a green result means the EA-controlled receipt set is coherent, not that EA owns every Chummer, Fleet, Property, media-provider, or design truth plane. `make verify-memorial-deploy-readiness` is the memorial pre-deploy guard: it fails closed unless memorial operator status and release authority agree the deploy can be trusted. `make verify-memorial-runtime-overlay` is the memorial deployment guard: it fails closed unless `/health/live` reports the memorial runtime overlay as mounted with a healthcheck slug, so public memorial gold claims cannot ride on a base stack that still has the surface disabled. `make verify-project-mode-runtime-memorial` is the mounted-surface guard: it proves the memorial public page and manifest are actually reachable once the overlay is present. `make verify-memorial-voice-stability` is the repeat deployed voice-loop check to run before a public memorial presentation claim. `make materialize-memorial-phrase-bank` refreshes the approved memorial audio/visible-copy phrase bank, `make materialize-memorial-operator-status` refreshes the operator-facing local/public-gold status card, and `make materialize-memorial-room-audio-gold-clean` records the final manual room/device receipt from a clean clone so unrelated worktree drift does not poison the proof.

Combined local readiness check:

```bash
make all-local
```

`make all-local` is a lightweight readiness pass that still checks release assets, flagship release readiness, and generated release artifact cleanliness. It does not require release-claim authority. Use `make release-preflight` for release-stage smoke and operator checks.

Deploys now default to a runtime hard-exit pass after the stack reports healthy. `scripts/deploy.sh` will run `bash scripts/runtime_hard_exit_gates.sh` unless `EA_RUN_RUNTIME_HARD_EXIT_GATES=0`. The runtime bundle is deploy-safe, includes the authoritative live-runtime release verifier, and excludes the deeper `smoke_api_principal.sh` contract lane; that lane remains part of `make hard-exit-gates`. When the deploy enables `MEMORIAL` mode, the same runtime bundle also runs `verify_memorial_runtime_overlay` plus `verify_project_mode_runtime.py --mode memorial` automatically before the deploy is allowed to finish.

Release preflight aggregate (asset checks + release-authority verification + authoritative runtime verification + flagship release-readiness verification + generated release artifact cleanliness + operator help + release smoke):

```bash
make release-preflight
```

`RELEASE_CHECKLIST.md` now includes explicit EA flagship truth-plane, release-authority, and release-readiness preflight lines to validate the browser proof, release gate seed, weekly pulse, Fleet journey gate, and deploy truth.

Memorial-mode deploy:

```bash
make verify-memorial-deploy-readiness
make deploy-ea-memorial
make verify-memorial-runtime-overlay
```

`make verify-memorial-deploy-readiness` should run before `make deploy-ea-memorial`. `make deploy-ea-memorial` is the first-class memorial runtime path. It sets `EA_DEPLOY_PRIMARY_MODE=MEMORIAL`, layers `docker-compose.memorial.yml`, and ensures the deploy context, release manifest, and project-mode receipts describe a memorial runtime instead of a generic EA core stack.
The memorial overlay bind-mounts `${EA_MEMORIAL_DATA_HOST_PATH:-./memorial_data}` read-only at `/data/memorial_data`; set that host path explicitly if the Manfred public/private memorial data lives outside the repo checkout.

Standalone-compatible service aliases for shared operator scripts:

- `PROPERTYQUARRY_API_SERVICE`
- `PROPERTYQUARRY_WORKER_SERVICE`
- `PROPERTYQUARRY_SCHEDULER_SERVICE`
- `PROPERTYQUARRY_DB_SERVICE`

## Smoke Exit Codes

`scripts/smoke_api.sh` uses these explicit non-zero codes for contract failures:

- `11`: rewrite response missing `execution_session_id`
- `12`: policy contract mismatch (`/v1/policy/evaluate` or blocked-policy assertion)
- `13`: runtime response missing an expected resource id (delivery or memory flow)

Other transport failures (for example `curl`) return their native non-zero exit codes.

## Stable public-ingress proxy identity

Run the public tunnel with `docker-compose.cloudflared.yml`. The base stack
attaches `ea-api` to the dedicated `ea_public_ingress` network, and the tunnel
uses the fixed peer address `172.31.254.2`. EA trusts only
`172.31.254.2/32`, so a Compose restart cannot silently change the tunnel peer
and make every public request fail with `421 host_not_allowed`.

Keep `EA_PUBLIC_INGRESS_CLOUDFLARED_IPV4` and
`EA_PUBLIC_INGRESS_TRUSTED_PROXY_CIDRS` aligned. For a governed memorial
promotion, set `EA_MEMORIAL_TRUSTED_PROXY_CIDRS` to the same exact `/32`.
Changing the subnet or peer address is a maintenance migration: validate the
rendered Compose configuration first and recreate the tunnel only in an
authorized deployment window.

## Manfred qualification authority

Manfred candidate creation and live promotion require a current root-owned
permit bound to the exact terminal schema-v6 VEXP epoch. During
`enforced_soak`, or when the state, stable lock, or permit is missing or
untrusted, stop: neither candidate creation nor live EA mutation is authorized.
Never create the JSON by hand and never substitute raw Docker commands.

Install the exact reviewed manager commit to
`/usr/local/libexec/ea/manage-manfred-vexp-mutation-permit`; never execute its
checkout source as root. From a reviewed root shell, invoke the installed file
only with `/usr/bin/python3 -I` under sanitized `env -i`, passing the explicit
absolute sentinel state path and numeric owner UID to both `issue` and `status`.
Run state-bound `status` immediately before candidate start and again
immediately before the scoped deployment. Run `revoke` after exact-revision
public memorial and priority 3D-tour proof. The pinned install commands and
receipt expectations are in
`docs/MANFRED_MEMORIAL_SCOPED_DEPLOY_RUNBOOK.md`.
