# EA main-branch hardening audit

Date: 2026-03-10
Audience: `executive-assistant` repo owners and the `solo-ea` fleet lane
Status: injected fleet feedback

## Summary

The current `main` branch is real progress and is worth building on seriously.

The strongest improvements are now clear:

* FastAPI app and container boundaries are more explicit.
* settings are structured instead of ad hoc
* non-health routers are request-auth protected when configured
* the runtime image is slimmer
* operator scripts around Postgres state are materially better
* CI now covers a broader runtime and storage surface

The next gains should come from hardening and decomposition, not from stuffing more behavior into the current core files.

## What is healthier now

* `create_app()` builds the container once, mounts health separately, and protects the main routers
* settings are grouped into core, runtime, storage, auth, policy, and channel sections
* the runtime is no longer pretending to be only a rewrite service
* Postgres tooling and operator scripts now explain state and disk usage more honestly
* the repo root still points toward a durable executive-assistant runtime with queued execution, approvals, routing, tools, delivery, and memory

## Priority order

1. Fix artifact durability and binary safety.
2. Fix `connector.dispatch` contract enforcement and central tool payload validation.
3. Add prod auth boot guards and explicit principal strategy.
4. Make worker topology explicit in compose.
5. Split `orchestrator.py`.
6. Split `tool_execution.py`.
7. Build memory context packs and conflict resolution.
8. Break up the giant smoke runtime API test.

## Primary required work

### 1. Artifact durability and storage design

This is the highest-priority hole.

Current risk:

* artifact metadata is durable in Postgres
* artifact bodies still land on local filesystem storage
* the default artifacts dir is effectively ephemeral
* storage refs use `file://` paths
* body writes are text-first even though artifacts already model `mime_type` and attachments
* default compose does not mount a dedicated durable artifact volume

Required direction:

* add a named `ea-artifacts` volume immediately
* wire `EA_ARTIFACTS_DIR` to that mount
* move toward a real artifact backend abstraction
* make storage handles opaque instead of storing `file://` paths as the durable contract
* make artifact persistence binary-safe

### 2. Tool execution contracts

Current risk:

* `connector.dispatch` declares one input contract but executes against a stricter hidden contract
* `binding_id` is required in execution flow but not required by the declared schema
* `allowed_channels` is declared but not centrally enforced before dispatch
* principal scoping rules differ between BrowserAct and connector dispatch paths

Required direction:

* require `binding_id` in the declared tool schema
* add central payload validation in the invocation path
* enforce `allowed_channels` deterministically before dispatch
* unify binding resolution and principal scoping rules across built-in tools
* make contract tests prove schema-versus-executor alignment

### 3. Auth and production strictness

Current risk:

* request auth becomes a no-op if `EA_API_TOKEN` is unset
* request context can silently fall back to a default or `"local-user"`
* prod readiness checks enforce Postgres more strongly than auth

Required direction:

* refuse prod startup without `EA_API_TOKEN`
* log the effective auth and principal strategy at startup
* allow default-principal fallback only outside prod
* make principal resolution explicit in prod instead of silently forgiving missing caller identity

### 4. Deployment topology

Current risk:

* code already supports worker-like roles
* default compose still presents only API plus DB
* operational truth therefore lags runtime truth

Required direction:

* add `ea-api`, `ea-worker`, and `ea-scheduler` services explicitly
* share the same durable artifact storage across them
* stop using the API process as the implicit background execution lane
* replace fixed idle sleep with bounded backoff or a wake-up mechanism

### 5. Service concentration

The biggest structural risk is now concentrated in a few oversized centers:

* `orchestrator.py`
* `tool_execution.py`
* `memory_runtime.py`
* `tests/smoke_runtime_api.py`

Required direction:

* extract `queue_runtime`, `step_executor`, `approval_runtime`, `human_task_runtime`, and `session_projection` out of the orchestrator
* split tool execution into adapter-focused modules
* separate memory CRUD from memory reasoning
* split the smoke runtime API file by domain scenario instead of keeping a giant pseudo-smoke monolith

### 6. Policy maturity

`PolicyDecisionService` is useful but still too thin for the stated EA vision.

Required direction:

* evolve policy toward `PolicyCompiler`, `ActionEvaluator`, `ApprovalEvaluator`, and `EgressEvaluator`
* model authority, data class, delivery preference, interruption budget, stakeholder sensitivity, and review class explicitly
* move from text-size and send-like heuristics toward assistant governance

### 7. Memory maturity

The memory substrate is valuable, but the next step is cognition rather than more raw tables.

Required direction:

* add `ContextPackBuilder`
* add `MemoryConflictResolver`
* add `CommitmentRiskEngine`
* add `StakeholderModelService`
* keep Postgres as runtime truth and use external projection surfaces only for approved projections

### 8. Naming and doc cleanup

Current drift:

* README still front-loads LTD and holding-company inventory above the runtime spine
* defaults still say `ea-rewrite` in places where the runtime is broader than rewrite flows
* one overlay still uses deprecated `EA_LEDGER_BACKEND`

Required direction:

* make the root README runtime-first
* move inventory-heavy material deeper into docs
* rename the default app/image posture to `ea-runtime` or `ea-kernel`
* use `EA_STORAGE_BACKEND` consistently

## Queue intent

Use this audit to steer the next EA slices in this order:

1. durable artifact storage and binary-safe artifact persistence
2. strict `connector.dispatch` schema, binding, principal, and channel enforcement
3. production auth/startup fail-closed behavior
4. explicit worker and scheduler topology in compose
5. orchestrator decomposition
6. tool execution decomposition
7. memory context-pack and conflict logic
8. smoke test breakup and runtime-first documentation cleanup
