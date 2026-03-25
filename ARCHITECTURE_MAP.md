# Architecture Map

## Runtime Entry Points

- API app factory: `ea/app/api/app.py`
- ASGI app export: `ea/app/main.py`
- Process runner / role switch: `ea/app/runner.py`

## Core Product Boundary

- Core product browser surface: `/`, `/product`, `/integrations`, `/security`, `/pricing`, `/docs`, `/get-started`, `/sign-in`, `/app/*`, `/admin/*`
- Optional experimental public utility routes: `/results/*`, `/tours/*`
- Product deployments should keep the experimental routes disabled unless explicitly required for a non-core use case

## Runtime Profile

- Settings shape: `ea/app/settings.py`
- Startup validation + runtime profile resolution: `ea/app/settings.py`
- Container composition + single-profile bootstrap: `ea/app/container.py`

## API Surface

- Health: `GET /health`
- Product browser data API: `/app/api/*`
- Channels: `/v1/channels/*`
- Connectors: `/v1/connectors/*`
- Delivery: `/v1/delivery/*`
- Evidence: `/v1/evidence/*`
- Human tasks: `/v1/human/*`
- Memory: `/v1/memory/*`
- Observations: `/v1/observations/*`
- Onboarding: `/v1/onboarding/*`
- Plans: `/v1/plans/*`
- Policy: `/v1/policy/*`
- Providers: `/v1/providers/*`
- Rewrite: `/v1/rewrite/*`
- Runtime: `/v1/runtime/*`
- Skills: `/v1/skills/*`
- Task contracts: `/v1/tasks/contracts/*`
- Tools: `/v1/tools/*`
- Codex-compatible façade: `/v1/models`, `/v1/responses`, `/v1/responses/{response_id}`, `/v1/responses/{response_id}/input_items`
- Codex lane routes live alongside the responses facade in `ea/app/api/routes/responses.py`.
  Concrete subroutes include `/v1/codex/core`, `/v1/codex/easy`, `/v1/codex/survival`, `/v1/codex/audit`, `/v1/codex/profiles`, and `/v1/codex/status`.
- Route roots: `ea/app/api/routes/`

## Core Domain Models

- Intent + execution: `IntentSpecV3`, `ExecutionSession`, `ExecutionEvent`
- Policy: `PolicyDecision`, `PolicyDecisionRecord`
- Memory: `MemoryCandidate`, `MemoryItem`
- Semantic context: `Entity`, `RelationshipEdge`
- Commitment context: `Commitment`
- Governance context: `AuthorityBinding`
- Delivery context: `DeliveryPreference`
- Follow-up context: `FollowUp`
- Deadline context: `DeadlineWindow`
- Stakeholder context: `Stakeholder`
- Decision context: `DecisionWindow`
- Communication context: `CommunicationPolicy`
- Follow-up rule context: `FollowUpRule`
- Interruption budget context: `InterruptionBudget`
- Channel runtime: `ObservationEvent`, `DeliveryOutboxItem`
- File: `ea/app/domain/models.py`

## Services

- Orchestration kernel: `ea/app/services/orchestrator.py`
- Planner: `ea/app/services/planner.py`
- Policy engine: `ea/app/services/policy.py`
- Task contract storage + serialization: `ea/app/services/task_contracts.py`
- Skill catalog: `ea/app/services/skills.py`
- Provider registry: `ea/app/services/provider_registry.py`
- Survival lane: `ea/app/services/survival_lane.py`
- Tool execution: `ea/app/services/tool_execution.py`
- Channel runtime: `ea/app/services/channel_runtime.py`
- Evidence runtime: `ea/app/services/evidence_runtime.py`
- Memory runtime: `ea/app/services/memory_runtime.py`
- LTD inventory helpers: `ea/app/services/ltd_inventory_api.py`, `ea/app/services/ltd_inventory_markdown.py`

## Repositories

- Artifacts: in-memory + postgres
- Task contracts: in-memory + postgres
- Observation events: in-memory + postgres
- Delivery outbox: in-memory + postgres
- Memory candidates/items: in-memory + postgres
- Entities/relationships/commitments: in-memory + postgres
- Governance/delivery/follow-up windows: in-memory + postgres
- Tool registry + connector bindings: in-memory + postgres
- Repository roots: `ea/app/repositories/`

## Operator Tooling

- Deploy: `scripts/deploy.sh`
- DB bootstrap: `scripts/db_bootstrap.sh`
- DB status: `scripts/db_status.sh`
- DB retention: `scripts/db_retention.sh`
- DB size: `scripts/db_size.sh`
- API smoke: `scripts/smoke_api.sh`
- Postgres smoke: `scripts/smoke_postgres.sh`
- LTD refresh: `scripts/refresh_ltds_via_api.py`, `scripts/refresh_ltds_from_inventory.py`
- Support bundle: `scripts/support_bundle.sh`
- CI workflow: `.github/workflows/smoke-runtime.yml`
