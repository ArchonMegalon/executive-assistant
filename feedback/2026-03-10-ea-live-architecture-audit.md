# EA live architecture audit

Date: 2026-03-10
Audience: repo owners and Codex worker agents
Status: injected follow-up from live repo audit

## Summary

The product architecture is ahead of the current code boundaries. This repo already has the shape of a durable executive-assistant runtime kernel, but it still carries three material risks:
- fail-open deployment and auth posture
- mixed subsystem fallback that blurs durability guarantees
- too much core behavior concentrated in a few overloaded abstractions

One correction to earlier audit posture: CI is stronger than it first looked. The checked-in workflow already covers a CI gate bundle, Postgres smoke, legacy migration smoke, and Postgres repository contract tests, and the `tests/` tree is broad.

## Primary required work

1. Make auth and startup fail closed.
- Add `validate_settings_or_raise(settings)` and call it from `create_app()` before `build_container()`.
- In `prod`, require `EA_API_TOKEN`, `EA_STORAGE_BACKEND=postgres`, and `DATABASE_URL`.
- Add an explicit `EA_ALLOW_UNAUTHENTICATED_LOCAL_DEV` guard for tokenless local-only operation.
- When auth is disabled, ignore caller-supplied `x-ea-principal-id` and force the configured default principal instead of allowing unauthenticated principal selection.
- Pin runtime/auth/storage env vars explicitly in compose or deployment manifests rather than relying on implicit defaults.

2. Resolve one runtime profile instead of letting each subsystem degrade independently.
- Introduce a single resolved `RuntimeProfile` with storage backend, auth requirement, durable contexts, and degraded contexts.
- Probe once and decide once.
- In `prod`, fail startup instead of partially degrading.
- Surface the resolved profile from `/health/ready` so operators can see the actual operating mode.

3. Stop treating `budget_policy_json` as the real schema.
- Introduce typed metadata models for retry policy, human review policy, skill catalog metadata, and workflow config.
- Parse the raw JSON once in the task-contract service and expose a typed view everywhere else.
- Replace planner and skill-service `.get(...)` reads with typed accessors.
- Restrict synthetic defaults so only `rewrite_text` gets a built-in default; unknown task keys should raise `unknown_task_contract` unless an explicit dev-only flag allows synthetic contracts.

4. Split `RewriteOrchestrator` before it becomes the permanent god class.
- Keep the current orchestrator as a facade for API stability.
- Extract an `ExecutionEngine` for session lifecycle, queue advancement, dependency resolution, and retry scheduling.
- Extract step handlers by step kind.
- Extract a read-focused `SessionQueryService` for snapshots and inspection views.
- Migrate one step kind at a time so the current test suite keeps providing regression coverage.

5. Make tool providers pluggable instead of hardcoding them in `ToolExecutionService`.
- Add a `ToolProvider` protocol for definition and handler registration.
- Move built-ins into provider modules.
- Keep `ToolExecutionService` focused on invocation lifecycle, policy checks, error normalization, and receipts.

6. Harden packaging and deployment.
- Choose one Dockerfile as the source of truth and delete or generate the other.
- Run as a non-root user.
- Add a real API healthcheck.
- Explicitly set critical runtime/auth/storage env vars in compose.
- Add a service healthcheck in `docker-compose.yml` so dependency health covers the API, not only Postgres.

## Structural direction to keep

Do not throw away the planner/task-contract/runtime-kernel direction. `PlannerService` already supports multiple workflow skeletons and the test suite is broad enough to support serious refactoring.

The cleaner long-term internal shape is:
- execution kernel: sessions, queue, step graph, receipts, artifacts
- governance: policy, approvals, human tasks, operator routing
- catalog: task contracts, skills, tools, connector bindings
- memory
- channels: observations and delivery

The route layout and README already hint at those seams. The service layer should mirror them more directly.

## Queue intent

Prioritize the next EA slices in this order:
1. fail-closed auth and startup validation
2. typed task-contract metadata instead of raw `budget_policy_json`
3. first orchestrator split seams with regression coverage frozen by tests
4. runtime profile resolution and explicit degraded-mode reporting
5. tool provider modularization
6. deployment and container hardening
