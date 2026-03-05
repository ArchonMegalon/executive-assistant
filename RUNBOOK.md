# Runtime Runbook

All runtime scripts that call HTTP endpoints resolve host port in this order:
1. `EA_HOST_PORT` from current shell env
2. `EA_HOST_PORT` from `.env`
3. fallback `8090`

## API Contract Summary

| Method | Route | Success | Error contracts |
|---|---|---|---|
| GET | `/health` | `200` | n/a |
| GET | `/health/live` | `200` | n/a |
| GET | `/health/ready` | `200` | `503 not_ready:*` |
| GET | `/version` | `200` | n/a |
| POST | `/v1/rewrite/artifact` | `200` | `400 text is required`, `403 policy_denied:*`, `409 policy_denied:approval_required` |
| GET | `/v1/rewrite/sessions/{session_id}` | `200` | `404 session not found` (returns events + steps + receipts + artifacts + costs, including `plan_compiled` event) |
| GET | `/v1/policy/decisions/recent` | `200` | n/a |
| GET | `/v1/policy/approvals/pending` | `200` | n/a |
| GET | `/v1/policy/approvals/history` | `200` | n/a |
| POST | `/v1/policy/approvals/{approval_id}/approve` | `200` | `404 approval_not_found` |
| POST | `/v1/policy/approvals/{approval_id}/deny` | `200` | `404 approval_not_found` |
| POST | `/v1/policy/approvals/{approval_id}/expire` | `200` | `404 approval_not_found` |
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
| POST | `/v1/connectors/bindings` | `200` | validation `422` |
| GET | `/v1/connectors/bindings` | `200` | validation `422` |
| POST | `/v1/connectors/bindings/{binding_id}/status` | `200` | `404 binding_not_found` |
| POST | `/v1/tasks/contracts` | `200` | validation `422` |
| GET | `/v1/tasks/contracts` | `200` | validation `422` |
| GET | `/v1/tasks/contracts/{task_key}` | `200` | `404 task_contract_not_found` |
| POST | `/v1/plans/compile` | `200` | validation `422` |
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

Error envelope for failures:
- `{ "error": { "code": "...", "message": "...", "details": ..., "correlation_id": "..." } }`

Auth:
- Set `EA_API_TOKEN=<token>` to require auth for all non-health routes.
- Use `Authorization: Bearer <token>` or `X-API-Token: <token>`.

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
| `scripts/support_bundle.sh` | `bash scripts/support_bundle.sh --help` | Build operator support bundle |
| `scripts/archive_tasks.sh` | `bash scripts/archive_tasks.sh --help` | Archive/prune task log Done rows |
| `scripts/verify_release_assets.sh` | `bash scripts/verify_release_assets.sh --help` | Verify release artifact completeness |

Combined index:

```bash
make operator-help
```

## CI Gate Summary

`smoke-runtime` workflow currently enforces:

- `make smoke-help`
- `make ci-local`
- `make test-api`
- `make verify-release-assets`

Milestone tracking linkage: `MILESTONE.json` feature tags include `ci_gate_bundle`, `release_preflight_bundle`, and `docs_verify_alias`.

Local mirror command:

```bash
make ci-gates
```

Release ops linkage: `RELEASE_CHECKLIST.md` includes `make ci-gates` as an optional local parity command.

## 1) Start Services

```bash
bash scripts/deploy.sh
# or
make deploy
```

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
```

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
```

## 4) Rewrite + Session Audit Smoke

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/artifact \
  -H 'content-type: application/json' \
  -d '{"text":"runbook smoke"}'
```

Use returned `execution_session_id`:

```bash
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/rewrite/sessions/<session_id>"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/policy/decisions/recent?session_id=<session_id>&limit=5"
```

## 5) Observation + Delivery Smoke

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/observations/ingest \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","channel":"email","event_type":"thread.opened","payload":{"subject":"Board prep"}}'
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
```

The smoke script now includes a blocked-policy assertion (`403` on oversized rewrite input).

## 8) Memory Candidate Promotion Smoke

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/candidates \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","category":"stakeholder_pref","summary":"CEO prefers concise updates","fact_json":{"tone":"concise"}}'
```

Promote using the returned `candidate_id`:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/candidates/<candidate_id>/promote \
  -H 'content-type: application/json' \
  -d '{"reviewer":"operator","sharing_policy":"private"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/items?limit=10&principal_id=exec-1"
```

Seed semantic entities/relationships:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/entities \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","entity_type":"person","canonical_name":"Alex Executive","attributes_json":{"role":"executive"}}'
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/relationships \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","from_entity_id":"<entity_a>","to_entity_id":"<entity_b>","relationship_type":"reports_to"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/entities?limit=10&principal_id=exec-1"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/relationships?limit=10&principal_id=exec-1"
```

Principal-scoped commitments:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/commitments \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Send board follow-up","details":"Draft by Friday","status":"open","priority":"high"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/commitments?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/commitments/<commitment_id>?principal_id=exec-1"
```

Principal-scoped authority bindings:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/authority-bindings \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","subject_ref":"assistant","action_scope":"calendar.write","approval_level":"manager","channel_scope":["email","slack"],"policy_json":{"quiet_hours_enforced":true},"status":"active"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/authority-bindings?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/authority-bindings/<binding_id>?principal_id=exec-1"
```

Principal-scoped delivery preferences:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/delivery-preferences \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","channel":"email","recipient_ref":"ceo@example.com","cadence":"urgent_only","quiet_hours_json":{"start":"22:00","end":"07:00"},"format_json":{"style":"concise"},"status":"active"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/delivery-preferences?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/delivery-preferences/<preference_id>?principal_id=exec-1"
```

Principal-scoped follow-ups:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-ups \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","stakeholder_ref":"ceo@example.com","topic":"Board follow-up","status":"open","due_at":"2026-03-07T09:00:00+00:00","channel_hint":"email","notes":"Send summary after prep call","source_json":{"source":"manual"}}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-ups?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-ups/<follow_up_id>?principal_id=exec-1"
```

Principal-scoped deadline windows:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/deadline-windows \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Board prep delivery window","start_at":"2026-03-07T08:30:00+00:00","end_at":"2026-03-07T10:00:00+00:00","status":"open","priority":"high","notes":"Draft must be ready before board sync","source_json":{"source":"manual"}}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/deadline-windows?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/deadline-windows/<window_id>?principal_id=exec-1"
```

Principal-scoped stakeholders:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/stakeholders \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","display_name":"Sam Stakeholder","channel_ref":"email:sam@example.com","authority_level":"approver","importance":"high","response_cadence":"fast","tone_pref":"diplomatic","sensitivity":"confidential","escalation_policy":"notify_exec","open_loops_json":{"board_follow_up":"open"},"friction_points_json":{"scheduling":"tight"},"last_interaction_at":"2026-03-06T15:30:00+00:00","status":"active","notes":"Needs concise summaries"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/stakeholders?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/stakeholders/<stakeholder_id>?principal_id=exec-1"
```

Principal-scoped decision windows:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/decision-windows \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","title":"Board response decision","context":"Choose timing and channel for reply","opens_at":"2026-03-06T08:00:00+00:00","closes_at":"2026-03-06T12:00:00+00:00","urgency":"high","authority_required":"exec","status":"open","notes":"Needs decision before board prep","source_json":{"source":"manual"}}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/decision-windows?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/decision-windows/<decision_window_id>?principal_id=exec-1"
```

Principal-scoped communication policies:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/communication-policies \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","scope":"board_threads","preferred_channel":"email","tone":"concise_diplomatic","max_length":1200,"quiet_hours_json":{"start":"22:00","end":"07:00"},"escalation_json":{"on_high_urgency":"notify_exec"},"status":"active","notes":"Board-facing communication defaults"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/communication-policies?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/communication-policies/<policy_id>?principal_id=exec-1"
```

Principal-scoped follow-up rules:

```bash
curl -fsS -X POST http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-up-rules \
  -H 'content-type: application/json' \
  -d '{"principal_id":"exec-1","name":"Board reminder escalation","trigger_kind":"deadline_risk","channel_scope":["email","slack"],"delay_minutes":120,"max_attempts":3,"escalation_policy":"notify_exec","conditions_json":{"priority":"high"},"action_json":{"action":"draft_follow_up"},"status":"active","notes":"Escalate if follow-up is late"}'
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-up-rules?principal_id=exec-1&limit=10"
curl -fsS "http://localhost:${EA_HOST_PORT:-8090}/v1/memory/follow-up-rules/<rule_id>?principal_id=exec-1"
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

## 15) Generate Support Bundle

```bash
bash scripts/support_bundle.sh
# optional log tail length
SUPPORT_LOG_TAIL_LINES=500 bash scripts/support_bundle.sh
# optional: skip DB logs
SUPPORT_INCLUDE_DB=0 bash scripts/support_bundle.sh
# optional: skip API logs
SUPPORT_INCLUDE_API=0 bash scripts/support_bundle.sh
# optional: skip DB size snapshot
SUPPORT_INCLUDE_DB_SIZE=0 bash scripts/support_bundle.sh
# optional: DB size snapshot top-table limit
SUPPORT_DB_SIZE_LIMIT=15 bash scripts/support_bundle.sh
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
# append + prune Done rows in TASKS_WORK_LOG.md
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
# docs-focused alias
make docs-verify
# docs + operator-help bundle
make release-docs
```

Use `make release-docs` as a pre-smoke documentation/usage pass before running `make release-preflight`.

Combined local readiness check:

```bash
make all-local
```

`make all-local` is a lightweight readiness pass. Use `make release-preflight` for release-stage smoke and operator checks.

Release preflight aggregate (asset checks + operator help + release smoke):

```bash
make release-preflight
```

`RELEASE_CHECKLIST.md` now includes an explicit milestone gate-tag parity preflight line to validate `MILESTONE.json` feature tags.

## Smoke Exit Codes

`scripts/smoke_api.sh` uses these explicit non-zero codes for contract failures:

- `11`: rewrite response missing `execution_session_id`
- `12`: blocked-policy path did not return expected `403`
- `13`: runtime response missing an expected resource id (delivery or memory flow)

Other transport failures (for example `curl`) return their native non-zero exit codes.
