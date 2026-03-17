# EA Hybrid Assistant Runtime

This repository is the EA runtime: a principal-scoped FastAPI control plane, a queue-backed execution plane, and a Postgres-backed context plane for approvals, human tasks, tools/connectors, observations, delivery, and memory.

## Runtime First

- Control plane: API/auth/config, operator scripts, health/version endpoints, and runtime docs
- Execution plane: sessions, steps, queue leasing, approvals, human routing, and worker roles
- Context plane: memory, stakeholders, commitments, follow-ups, evidence, skills, and task contracts
- Runtime source of truth: Postgres is the durable ledger for sessions, steps, queue rows, approvals, outbox, and memory

## Run It

```bash
cp .env.example .env
# edit .env values
bash scripts/deploy.sh
bash scripts/db_bootstrap.sh
```

For an explicit durable deployment profile, layer the prod override on top of the base compose:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

To expose the Gemini Vortex-backed Responses model aliases locally, layer the Gemini override onto the API service so the container can execute the host Gemini CLI with the host credential directory:

```bash
docker compose -f docker-compose.yml -f docker-compose.gemini.yml up -d --force-recreate ea-api
```

Worker topology is explicit in [docker-compose.yml](/docker/EA/docker-compose.yml):

- `ea-api`: HTTP API and inline queue drain for request-scoped work
- `ea-worker`: background queue drainer for general execution leases
- `ea-scheduler`: background queue drainer reserved for scheduled or dedicated lease ownership
- `ea-db`: Postgres runtime state

Then open `http://localhost:8090/health`.

## Runtime Docs

- Operator runbook: [RUNBOOK.md](/docker/EA/RUNBOOK.md)
- Architecture map: [ARCHITECTURE_MAP.md](/docker/EA/ARCHITECTURE_MAP.md)
- HTTP examples: [HTTP_EXAMPLES.http](/docker/EA/HTTP_EXAMPLES.http)
- Environment/profile guidance: [ENVIRONMENT_MATRIX.md](/docker/EA/ENVIRONMENT_MATRIX.md)
- Release notes: [CHANGELOG.md](/docker/EA/CHANGELOG.md)
- Milestone/state model: [MILESTONE.json](/docker/EA/MILESTONE.json)
- Skills catalog: [SKILLS.md](/docker/EA/SKILLS.md)
- Workspace inventory and LTD notes: [LTDs.md](/docker/EA/LTDs.md)
- BrowserAct content-template exporter: `python3 scripts/generate_browseract_content_templates.py`
- Gate-bundle hardening flags are tracked in `MILESTONE.json` release tags.
- Release preflight checklist includes milestone release-tag parity verification in `RELEASE_CHECKLIST.md`.
- `bash scripts/refresh_ltds_from_inventory.sh --input <inventory.json> --write` can rewrite the LTD discovery table from structured BrowserAct inventory output.
- `bash scripts/refresh_ltds_via_api.sh --binding-id <browseract-binding-id> --service-name BrowserAct --write` can execute the `ltd_inventory_refresh` skill and rewrite the LTD discovery table through the local API.

## Runtime Spine

- `app.main` exposes a FastAPI app
- `/health`, `/health/live`, `/health/ready`, `/version` provide liveness/readiness/version probes
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
  - `POST /v1/codex/repair` (bounded-fix lane, forced `ea-coder-fast`)
  - `POST /v1/codex/groundwork` (Gemini groundwork lane, forced `ea-groundwork-gemini`)
  - `POST /v1/codex/review-light` (cheap review lane, forced `ea-review-light`)
  - `POST /v1/codex/survival` (slow backup lane, forced `ea-coder-survival`, background/poll only in v1)
  - `POST /v1/codex/audit` (jury lane, forced `ea-audit-jury`)
  - stream mode via `Accept: text/event-stream`
  - survival mode is intentionally non-streaming in v1; create returns an `in_progress` response object and clients poll `GET /v1/responses/{response_id}` until completion
  - `GET /v1/models` returns the public EA aliases plus the currently configured upstream model IDs so Codex can target concrete provider backends when needed.
  - `GET /v1/responses/_provider_health` and `GET /v1/codex/profiles` expose account-name attribution, owner-ledger metadata matched by hash or stable slot/account identifiers, latest explicit probe result, observed `remaining_credits` / `required_credits`, per-slot `observed_consumed_credits` / `observed_success_count`, aggregate `estimated_remaining_credits_total` / `remaining_percent_of_max`, rolling `estimated_burn_credits_per_hour` / `estimated_hours_remaining_at_current_pace`, and deleted-key quarantine state without returning raw API secrets.
  - `python3 scripts/sync_onemin_owner_ledger.py --write` refreshes `config/onemin_slot_owners.json` from the current `ONEMIN_AI_API_KEY*` values while preserving the existing owner roster metadata by slot/account.
  - `GET /v1/models` includes the Gemini Vortex-backed `ea-gemini-flash` public alias, the groundwork aliases `ea-groundwork-gemini` and `ea-groundwork`, plus the concrete `gemini-3-flash-preview` model id when that backend is configured.
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
- `/v1/skills*` promotes those task contracts into product-facing executive skills with explicit workflow, memory, authority, provider-hint, human-policy, and evaluation metadata, including the Gemini Vortex-backed `chummer6_public_writer` lane for audience-safe guide copy, the Gemini Vortex-backed `chummer6_visual_director` lane for style-epoch and scene-ledger-driven image direction, the BrowserAct-backed `browseract_bootstrap_manager` lane for on-demand workflow-spec generation across prompt-tool and page-extract templates, and the Gemini-assisted `browseract_workflow_repair_manager` lane for self-healing broken BrowserAct specs
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
- `/v1/skills` now projects a first-class skill catalog layer over task contracts, so executive capabilities like `meeting_prep`, `ltd_inventory_refresh`, the BrowserAct-backed `browseract_bootstrap_manager`, the repair-focused `browseract_workflow_repair_manager`, the Gemini Vortex-backed `chummer6_public_writer`, and the Gemini Vortex-backed `chummer6_visual_director` can persist product-facing metadata (`memory_reads`, `memory_writes`, authority/tool/human/provider policy, evaluation cases, and workflow template selection) without introducing a second storage system; `chummer6_public_writer` records reviewed public-copy facts, `chummer6_visual_director` records reviewed style-epoch plus scene-ledger facts so the art direction can remember what it already rendered, `SKILLS.md` tracks the current catalog, and `GET /v1/skills?provider_hint=BrowserAct` filters the catalog by LTD-backed provider hints
- Chummer6 text generation now routes through EA + Gemini Vortex only. If that lane is unavailable, the worker fails instead of quietly falling back to Codex.
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
- Set `EA_DEFAULT_PRINCIPAL_ID=<principal>` to define the fallback request principal when `X-EA-Principal-ID` is omitted (default `local-user`).
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
- Common targets: `make deploy`, `make bootstrap`, `make db-status`, `make db-size`, `make db-retention`, `make operator-summary`, `make smoke-api`, `make smoke-postgres`, `make smoke-postgres-legacy`, `make release-smoke`, `make ci-gates-postgres`, `make ci-gates-postgres-legacy`, `make all-local`, `make verify-release-assets`, `make release-docs`, `make release-preflight`
- OpenAPI export/diff: `scripts/export_openapi.sh`, `scripts/diff_openapi.sh`, `make openapi-export`, `make openapi-diff`
- Release checklist: `RELEASE_CHECKLIST.md`
Snapshot pruning is available via `scripts/prune_openapi.sh` or `make openapi-prune`.
Endpoint inventory can be printed via `scripts/list_endpoints.sh` or `make endpoints`.
Version fingerprint can be printed via `scripts/version_info.sh` or `make version-info`.
`scripts/version_info.sh` now also prints milestone capability-status counts and release tags from `MILESTONE.json`.
Operator summary can be printed via `scripts/operator_summary.sh` or `make operator-summary`.
The operator summary includes smoke, readiness, CI parity, release/support, and task-archive shortcuts.
`bash scripts/operator_summary.sh --help` prints the usage contract and is included in `make operator-help`.
Operator script usage index can be printed via `make operator-help`.
Endpoint/version/OpenAPI helper scripts also expose `--help` and are included in `make operator-help`.
Support bundle export is available via `scripts/support_bundle.sh` or `make support-bundle`.
Support bundles apply baseline redaction for common secret/token/password patterns.
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
One-command local CI gate bundle is available via `make ci-gates`.
Combined local API+Postgres parity run is available via `make ci-gates-postgres`.
Combined local API+Postgres legacy-migration parity run is available via `make ci-gates-postgres-legacy`.
Release asset integrity can be checked via `scripts/verify_release_assets.sh` or `make verify-release-assets`.
Docs-focused alias for the same check: `make docs-verify`.
Docs + operator help aggregate: `make release-docs`.
Release preflight aggregate is available via `make release-preflight`.
Recommended sequencing: run `make release-docs` before `make release-preflight`.
One-command local readiness check: `make all-local`.
`make all-local` is a lighter local readiness pass; use `make release-preflight` for release-stage smoke + operator checks.
CI gate sequence is documented in `RUNBOOK.md` and includes the API gate bundle (`smoke-help`, `ci-local`, `test-api`, release-asset verification), Postgres-backed smoke and repository-contract jobs (`scripts/smoke_postgres.sh`, `scripts/test_postgres_contracts.sh`), and a legacy migration-regression job (`bash scripts/smoke_postgres.sh --legacy-fixture`).
Shell script lint config is tracked in `.shellcheckrc`.
