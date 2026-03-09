# EA Runtime Audit + Dev Change Guide

Date: 2026-03-09
Audience: `executive-assistant` repo owners and worker agents
Scope: `ArchonMegalon/executive-assistant` runtime repo itself

Understood. This feedback is for the EA runtime repo itself under `ArchonMegalon/executive-assistant`, not any surrounding dev-hub or fleet.

## Executive audit

This repo is now materially more mature than the earlier rewrite audit. It has a principal-scoped FastAPI runtime, structured settings with production fallback guards, request auth and principal-scope enforcement, a containerized dependency graph, a queued execution kernel, approvals, human-task routing, a tool/connector registry, a large principal-scoped memory domain, Postgres-backed repos for most of those surfaces, migrations through `v0_31`, smoke scripts for memory and Postgres, and a meaningfully expanded test suite.

That is no longer a toy assistant shell. It is a serious assistant kernel.

The strongest parts are clear:

- the runtime boundary is cleaner
- `get_settings()` exists
- production mode forbids silent storage fallback
- non-health routes are auth-protected
- body/query principal mismatches are rejected
- the app returns a consistent JSON error envelope with a correlation ID
- the Docker image is slimmer and no longer installs the old heavy runtime dependencies
- compose is a simple `ea-api + ea-db` baseline
- the repo includes operator-facing scripts like `db_status.sh`, `db_size.sh`, and `smoke_postgres.sh`
- the repo explicitly documents that `/var/lib/docker/volumes/.../ea_pgdata` is disk-backed Postgres state, not RAM

The planning and execution story is also much stronger than before. The runtime now includes execution sessions, events, steps, queue items, receipts, costs, approvals, human tasks, task contracts, skills, tools, connectors, plans, policy decisions, observations, delivery outbox rows, and memory objects such as entities, relationships, commitments, stakeholders, deadlines, follow-ups, delivery preferences, authority bindings, and interruption budgets.

The planner supports typed workflow templates and can inject human-review steps from task-contract metadata. The orchestrator supports async queueing, approvals, human-task blocking, step retries with backoff, and dependency-aware step execution.

The repo is also much more test-backed than before. There is still only one workflow file, but it now runs multiple CI jobs including `make ci-gates`, `smoke_postgres.sh`, the legacy-fixture smoke path, and Postgres contract tests. The test tree is no longer a single smoke file; it now includes API, repository, integration, planner, policy, queue retry, memory, scope, step I/O, task-contract, skills, and OpenAPI example tests.

Baseline verdict: this is a real EA kernel now.

## The core problems

### 1. Architectural concentration

`orchestrator.py` is still enormous and carries too many responsibilities at once:

- session lifecycle
- queue semantics
- retry scheduling
- dependency projection
- policy interaction
- approval pauses
- human-task routing
- planner invocation
- artifact persistence
- response projection

This is the single biggest design risk in the repo.

### 2. Model concentration

`domain/models.py` is a useful inventory of the runtime, but it has become an omnibus file for:

- execution
- policy
- memory
- channels
- tools
- planning
- human tasks
- operators

That is survivable at kernel stage and toxic once the assistant adds real connector breadth, proactive intelligence, and multi-role worker behavior.

### 3. Topology drift

`runner.py` clearly supports non-API execution roles by polling `orchestrator.run_next_queue_item(lease_owner=role)`, but the committed compose topology still only expresses `ea-api` and `ea-db`.

The code already thinks in terms of background workers. The default deployment picture does not yet show them.

### 4. Policy is still mostly a hand-written rule engine

It now considers tool allow-lists, approval class, text length, risk class, budget class, connector use, send actions, and channel-specific send paths. That is a solid seed. It is still fundamentally a deterministic ruleset rather than a full policy system over:

- data classes
- authority
- egress
- retention
- action scope

That will be too weak for a fully autonomous EA.

### 5. Memory is broad but still mostly infrastructural

`MemoryRuntimeService` now has a serious surface area for:

- candidates
- memory items
- entities
- relationships
- commitments
- communication policies
- decision windows
- deadline windows
- stakeholders
- authority bindings
- delivery preferences
- follow-ups
- follow-up rules
- interruption budgets

But the service is still primarily an upsert/list/get facade over those repositories. The repo has built the memory substrate; it has not yet built the context engine that reasons over it.

### 6. The root README is doing too much

It now combines runtime docs, endpoint inventory, skill/task descriptions, and LTD inventory / BrowserAct / Teable notes. That makes the repo harder to understand than it needs to be and muddies the architecture story. The runtime itself is the product here; inventory tables should not dominate the first read.

### 7. Teable is not where the runtime ledger should go

The runtime is clearly designed around Postgres for:

- sessions
- steps
- queue items
- outbox
- policy
- approvals
- memory tables
- artifacts

`ea_pgdata` is correct as the on-disk state for the assistant kernel. If Teable exists in the system at all, it should be an optional reviewed projection of approved semantic memory, not the execution plane.

## Non-negotiable architecture rules

1. Postgres remains the runtime source of truth.
2. Everything meaningful must be explainable as: observation -> plan -> steps -> policy decisions -> side effects -> receipts -> memory candidates.
3. No more central growth in `orchestrator.py`.
4. Worker topology must be explicit.
5. Memory must graduate from CRUD to reasoning.

## Milestone 0 — Make the repo truthful, bounded, and easier to operate

### Goal

Turn the repo into a clean EA runtime repo first. Remove ambiguity, doc sprawl, and legacy naming before adding more intelligence.

### Architectural design

The runtime should present itself as three things only:

- control plane: API, auth, config, docs, operator scripts
- execution plane: sessions, queue, steps, policy, approvals, workers
- context plane: memory, stakeholders, commitments, follow-ups, skills

Everything else should move below that line.

### Implementation instructions

- Rewrite the root README so the first screen is:
  - what the EA runtime is
  - how to run it
  - what roles exist
  - what state lives in Postgres
  - where detailed docs live
- Move LTD inventory, BrowserAct inventory refresh, and similar workspace-specific material into `docs/inventory/` or `LTDs.md` only.
- Remove the deprecated `EA_LEDGER_BACKEND` from `docker-compose.memory.yml` and any remaining scripts. `settings.py` already treats it as a deprecated alias; stop exercising the deprecated path in the default operator entrypoints.
- Split `domain/models.py` into modules:
  - `domain/execution.py`
  - `domain/policy.py`
  - `domain/tools.py`
  - `domain/planning.py`
  - `domain/memory.py`
  - `domain/human.py`
  - `domain/channels.py`
- Add ADRs:
  - ADR-001 runtime source of truth = Postgres
  - ADR-002 Teable is optional projection, not runtime
  - ADR-003 principal scope boundary
  - ADR-004 queue-based execution and async workers
- Add `docs/topology.md` that explicitly distinguishes API role vs worker roles.

### Tests

- settings compatibility tests for `EA_STORAGE_BACKEND` and the deprecated alias
- README endpoint inventory check against the actual mounted routers
- import/boot tests after the `domain/` split
- operator-doc link and command smoke tests

### Done when

A new engineer can understand the runtime without reading the entire README dump, and the repo no longer advertises or defaults to deprecated config names.

## Milestone 1 — Extract the execution kernel from the orchestrator

### Goal

Preserve current behavior while breaking `orchestrator.py` into stable subsystems.

### Architectural design

Create an explicit execution kernel with:

- `SessionRuntime`
- `QueueRuntime`
- `StepExecutor`
- `PauseResumeRuntime`
- `ApprovalRuntime`
- `HumanEscalationRuntime`
- `SessionProjectionService`

`RewriteOrchestrator` should become a thin facade over those services.

### Implementation instructions

- Move queue item claiming, lease handling, retry backoff, and queue rescheduling into `services/execution/queue_runtime.py`.
- Move approval-block detection and session pause/resume behavior into `services/execution/pause_resume.py`.
- Move step execution and dependency resolution into `services/execution/step_executor.py`.
- Move session envelope assembly into `services/execution/projection.py`.
- Add worker roles to compose:
  - `ea-api`
  - `ea-worker`
  - `ea-scheduler`
- Add stale-lease reaping and worker-heartbeat support if not already present in the queue layer.

### Tests

- golden replay tests: current rewrite flow before/after refactor must project identical sessions
- concurrent worker lease tests
- retry backoff tests
- blocked-dependency tests
- approval pause/resume tests
- queue starvation tests

### Done when

`orchestrator.py` falls below roughly 600 lines and becomes coordination-only, while all current behavior still passes.

## Milestone 2 — Replace rule checks with a real policy and authority engine

### Goal

Turn policy from a set of conditions into a real decision system for autonomy.

### Architectural design

Introduce a first-class policy model with:

- `ActionClass`
- `DataClass`
- `ApprovalPolicy`
- `EgressPolicy`
- `RetentionPolicy`
- `AuthorityProfile`
- `TrustTier`
- `CommunicationPolicyPack`

The runtime should decide actions using:

principal + task + tool + channel + data class + authority + stakeholder + interruption budget + time window

### Implementation instructions

- Keep `PolicyDecisionRecord`, but extend it with:
  - `matched_rule_ids`
  - `data_classes`
  - `egress_decision`
  - `redactions_applied`
  - `authority_basis`
  - `why_blocked`
- Add policy storage:
  - `policy_packs`
  - `policy_rules`
  - `authority_profiles`
  - `data_classifications`
- Refactor `PolicyDecisionService` into:
  - `PolicyCompiler`
  - `PolicyEvaluator`
  - `ApprovalEvaluator`
  - `EgressEvaluator`
- Integrate `AuthorityBinding`, `CommunicationPolicy`, `DeliveryPreference`, and `InterruptionBudget` directly into policy evaluation.
- Add a simulation endpoint:
  - `POST /v1/policy/simulate`

### Tests

- policy matrix tests across tool/channel/task/risk combinations
- property tests: stricter risk or lower authority may never widen permission
- egress-deny tests
- principal-scope isolation tests
- quiet-hours/interruption-budget tests
- approval explanation tests

### Done when

Every side effect, every external tool call, and every model-egress path flows through the same decision engine and produces an explainable record.

## Milestone 3 — Build the real tool and connector execution plane

### Goal

Turn the current tool registry and built-in handlers into the assistant’s acting layer.

### Architectural design

Separate three concerns:

- tool contracts: what a tool is allowed to do
- connector bindings: which external accounts are available
- execution adapters: how work is actually performed

### Implementation instructions

- Keep `ToolRuntimeService` responsible for registry and connector binding persistence only.
- Make `ToolExecutionService` the adapter router, and split its built-ins into:
  - `services/tools/artifact_repository.py`
  - `services/tools/browseract_extract.py`
  - `services/tools/browseract_inventory.py`
  - `services/tools/connector_dispatch.py`
- Expand connector breadth beyond BrowserAct and generic dispatch:
  - `email.list_threads`
  - `email.create_draft`
  - `email.send`
  - `calendar.find_conflicts`
  - `calendar.create_event`
  - `calendar.move_event`
  - `slack.post_message`
  - `contacts.lookup`
- Make `connector.dispatch` a low-level fallback, not the main user-facing tool.
- Ensure every tool execution writes:
  - execution step
  - tool receipt
  - evidence object if applicable
  - outbox row if dispatching
- Add connector health and auth status transitions to operator views.

### Tests

- contract tests per tool adapter
- fake external service integration tests
- idempotency tests for sends
- timeout and retry tests
- receipt-completeness tests
- policy-tool alignment tests
- dead-letter recovery tests

### Done when

The EA can do at least these end-to-end, with receipts:

- draft and send an email
- schedule or move a meeting
- post a Slack or Telegram update
- persist an artifact and attach evidence
- run BrowserAct inventory extraction through the same execution plane

## Milestone 4 — Turn the memory substrate into a context engine

### Goal

Convert the current memory CRUD layer into the assistant’s real context system.

### Architectural design

Keep Postgres as the canonical state store, but add a context engine on top:

- `MemoryCandidateExtractor`
- `MemoryConflictResolver`
- `ContextPackBuilder`
- `GraphQueryService`
- `CommitmentRiskEngine`
- `StakeholderModelService`

### Implementation instructions

- Add a promotion pipeline:
  - session/step/evidence/human output -> memory candidate -> review/auto-approve -> memory item/entity/relationship/commitment
- Add conflict/versioning tables:
  - `memory_conflicts`
  - `fact_versions`
  - `entity_aliases`
- Add temporal semantics:
  - valid-from / valid-to for relationships, commitments, preferences, delivery preferences, authority bindings
- Build reusable context packs for planning:
  - stakeholder summary
  - active commitments
  - deadline risks
  - interruption rules
  - communication preferences
- Use the existing domain objects as the canonical graph substrate.
- If Teable returns later, implement it only as:
  - approved memory item -> Teable projection

### Tests

- promotion approval/rejection tests
- dedupe and conflict resolution tests
- temporal retrieval tests
- policy-scoped retrieval tests
- deletion/forgetting tests
- leakage tests across principals
- context-pack regression tests on fixed scenarios

### Done when

The planner can ask for a context pack and get a clean, policy-scoped summary of stakeholders, commitments, follow-ups, authority, and timing rather than raw ledger history.

## Milestone 5 — Evolve task contracts into a real skill and plan graph system

### Goal

Make skills and plans the true programming model of the assistant.

### Architectural design

Use the current `TaskContract`, `SkillContract`, `PlanStepSpec`, `PlanSpec`, and workflow templates as the seed of a full plan graph system with reusable subgraphs and versioned skills.

Target architecture:

- `IntentCompiler`
- `WorkflowResolver`
- `PlanGraphCompiler`
- `PlanValidator`
- `PlanSimulator`
- `SkillVersionRegistry`

### Implementation instructions

- Keep current workflow templates as seed macros and promote them into reusable graph fragments.
- Split planner code into:
  - `intent_compiler.py`
  - `workflow_templates.py`
  - `plan_graph.py`
  - `plan_validation.py`
  - `plan_simulation.py`
- Add skill versioning and migration metadata.
- Make `skill_key` first-class across every route, projection, and receipt.
- Add dry-run/simulate endpoints that compile and validate plans without execution.
- Introduce evidence packs as explicit plan inputs/outputs.

### Tests

- compile/validate snapshot tests
- backward-compat tests for skill versions
- graph cycle and dependency validation tests
- step I/O declaration invariant tests
- async queue acceptance tests
- simulation-vs-execution parity tests

### Done when

A new executive capability is added by shipping a skill contract and plan graph, not by editing the orchestrator.

## Milestone 6 — Build the human collaboration operating system

### Goal

Turn human-task routing into a true operator desk for the assistant.

### Architectural design

Build the human collaboration OS on top of the existing human-task substrate with:

- `HumanRoutingService`
- `OperatorCapacityService`
- `ReviewFeedbackService`
- `EscalationPolicyService`

### Implementation instructions

- Extend operator profiles with:
  - active load
  - availability
  - specialties
  - trust tier
  - quality score
  - average SLA performance
- Add assignment policy objects:
  - role match
  - skill-tag match
  - trust minimum
  - auto-assign strategy
  - escalation deadline
- Build automatic routing:
  - suggested operators
  - recommended operator
  - auto-assign if unique and trusted
- Make human-generated outputs schema-validated before plan resume.
- Add review feedback loops so human performance can refine routing and trust.

### Tests

- auto-assign correctness tests
- fairness/load-balancing tests
- SLA breach escalation tests
- manual override tests
- returned-packet resume tests
- assignment-history completeness tests
- human-output schema validation tests

### Done when

High-risk or low-confidence work can be handed to a human operator, worked, reassigned, reviewed, and resumed through the same assistant kernel without manual patching.

## Milestone 7 — Add proactive executive intelligence

### Goal

Fulfill the actual EA promise: not just reactive execution, but proactive support.

### Architectural design

Build a proactive layer that scans:

- observations
- commitments
- follow-ups
- deadline windows
- outbox failures
- stakeholder activity
- approvals waiting too long
- calendar conflicts
- interruption budgets

It should produce `proactive_candidates` scored by:

- urgency
- impact
- confidence
- interruption cost
- authority to act
- stakeholder importance

### Implementation instructions

- Add scheduler/proactive worker roles.
- Create tables:
  - `proactive_candidates`
  - `intervention_decisions`
  - `brief_jobs`
  - `alert_budgets`
- Start with five proactive scenarios:
  1. missed follow-up risk
  2. approaching deadline with no movement
  3. failed delivery requiring escalation
  4. stakeholder thread heating up
  5. daily executive brief generation
- Run all of them in shadow mode first.
- Use existing memory surfaces as the scoring substrate.

### Tests

- replay tests over seeded scenarios
- false-positive budget tests
- quiet-hours suppression tests
- budget exhaustion tests
- draft-vs-action policy tests
- human comparison tests in shadow mode
- daily brief correctness and coverage tests

### Done when

The assistant reliably surfaces real executive risks before the user asks, without spamming or violating policy.

## Milestone 8 — Productionize the assistant as a full system

### Goal

Make the EA durable, operable, and ready for real continuous use.

### Architectural design

Express the runtime as an actual deployment topology:

- `ea-api`
- `ea-worker`
- `ea-scheduler`
- optional connector listener roles
- Postgres
- artifact storage
- metrics/logging stack

### Implementation instructions

- Expand compose/Kubernetes manifests to include dedicated workers.
- Move artifacts to a proper object/file store abstraction if inline DB usage starts to dominate size.
- Add table partitioning/retention for:
  - execution events
  - queue history
  - sent/dead-lettered outbox
  - old receipts and evidence blobs
- Extend `db_size.sh` and `db_retention.sh` into regular operator jobs.
- Add observability for:
  - queue depth
  - step latency
  - retry counts
  - approval dwell time
  - human-task backlog
  - proactive candidate rates
- Build backup/restore and migration rehearse scripts.

### Tests

- load tests
- soak tests
- chaos tests for worker crash/restart
- backup/restore tests
- migration-forward tests
- performance regression gates
- support-bundle smoke tests

### Done when

The assistant can run for weeks as a service, not just as a development runtime.

## Milestone 9 — Vision complete: the Apex EA runtime

### Goal

At the end of this milestone, the EA vision is fulfilled.

### What fulfilled means

After this milestone, the assistant should be able to:

- accept observations and requests across channels
- compile them into auditable plans
- execute through a queue-backed step engine
- enforce policy, approvals, and authority boundaries
- route uncertain or high-risk work to human operators
- use durable context from memory, stakeholders, commitments, and follow-ups
- act through typed connectors and tools
- produce receipts, evidence, and artifacts for every meaningful action
- proactively surface risks and opportunities
- operate durably with observability, retention, and operator tooling

### Architectural design

At that point, the architecture is three clean planes:

- execution plane
- context plane
- agency plane

### Implementation instructions

- Add full scenario suites:
  - receive an inbound issue -> draft response -> human review -> send -> memory update
  - detect missed follow-up -> propose reminder -> schedule or send
  - generate daily brief from observations + commitments + delivery failures + human work
  - ingest account inventory -> update runtime-facing inventory artifacts
- Add benchmark/evaluation harnesses for:
  - task success
  - policy compliance
  - operator routing quality
  - proactive acceptance rate
  - executive brief usefulness
- Establish release gates so no milestone ships without:
  - schema
  - services
  - routes
  - docs
  - tests
  - operator scripts

### Tests

- full end-to-end scenario replay suite
- benchmark regression suite
- cross-principal isolation suite
- executive-brief scenario suite
- multi-step proactive intervention suite
- release artifact verification suite

### Done when

The assistant is no longer just a runtime with many good tables. It is a policy-governed, memoryful, proactive executive assistant system.

## Immediate suggestions to the dev

1. Split `orchestrator.py` before adding more features.
2. Split `domain/models.py` into bounded modules.
3. Clean the root README so runtime docs come first.
4. Stop using `EA_LEDGER_BACKEND` in default overlays/scripts and canonicalize on `EA_STORAGE_BACKEND`.
5. Add worker services to compose.
6. Promote policy into a structured rule/evaluator subsystem.
7. Turn memory into context packs and temporal reasoning, not just CRUD.
8. Split `tool_execution.py` into adapters.
9. Keep Postgres as runtime truth. Do not chase Teable as the execution backend.
10. Use the existing test momentum. Add replay, load, chaos, and scenario suites before adding smarter autonomy.

## Final judgment

The current repo is good enough to justify serious investment. It already has the right primitives for a next-generation EA:

- principal scope
- queue-backed execution
- approvals
- human routing
- typed plans
- tools/connectors
- a rich memory domain

It is not yet vision-complete because:

- the intelligence layer is still trapped inside oversized files
- the deployment topology is under-expressed
- policy is still mostly rule-based
- memory is still more substrate than cognition

The right move now is not to add another feature. It is to stabilize the architecture into three planes - execution, context, and agency - then let the later milestones unlock the full EA behavior on top of that.
