# Runtime Runbook

All runtime scripts that call HTTP endpoints resolve host port in this order:
1. `EA_HOST_PORT` from current shell env
2. `EA_HOST_PORT` from `.env`
3. fallback `8090`

## API Contract Summary

| Method | Route | Success | Error contracts |
|---|---|---|---|
| GET | `/health` | `200` | n/a |
| POST | `/v1/rewrite/artifact` | `200` | `400 text is required`, `403 policy_denied:*`, `409 policy_denied:approval_required` |
| GET | `/v1/rewrite/sessions/{session_id}` | `200` | `404 session not found` |
| GET | `/v1/policy/decisions/recent` | `200` | n/a |
| POST | `/v1/observations/ingest` | `200` | validation `422` |
| GET | `/v1/observations/recent` | `200` | validation `422` |
| POST | `/v1/delivery/outbox` | `200` | validation `422` |
| GET | `/v1/delivery/outbox/pending` | `200` | validation `422` |
| POST | `/v1/delivery/outbox/{delivery_id}/sent` | `200` | `404 delivery_not_found` |
| POST | `/v1/channels/telegram/ingest` | `200` | validation `422` |

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

Check table presence/counts:

```bash
bash scripts/db_status.sh
# or
make db-status
```

## 3) Health Check

```bash
curl -fsS http://localhost:${EA_HOST_PORT:-8090}/health
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
```

The smoke script now includes a blocked-policy assertion (`403` on oversized rewrite input).

## 8) Export OpenAPI Snapshot

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

## 9) Optional Local Pre-Commit Hook

```bash
mkdir -p .githooks
cp .githooks/pre-commit.example .githooks/pre-commit
chmod +x .githooks/pre-commit
git config core.hooksPath .githooks
```

## 10) Print Endpoint Inventory

```bash
bash scripts/list_endpoints.sh
# or
make endpoints
```

## 11) Print Version Fingerprint

```bash
bash scripts/version_info.sh
# or
make version-info
```

## 12) Print Operator Summary

```bash
bash scripts/operator_summary.sh
# or
make operator-summary
```

## 13) Generate Support Bundle

```bash
bash scripts/support_bundle.sh
# optional log tail length
SUPPORT_LOG_TAIL_LINES=500 bash scripts/support_bundle.sh
# optional: skip DB logs
SUPPORT_INCLUDE_DB=0 bash scripts/support_bundle.sh
# optional: skip API logs
SUPPORT_INCLUDE_API=0 bash scripts/support_bundle.sh
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

## 14) Archive Completed Task Rows

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

## 15) Verify Release Assets

```bash
bash scripts/verify_release_assets.sh
# or
make verify-release-assets
```

Combined local readiness check:

```bash
make all-local
```

## Smoke Exit Codes

`scripts/smoke_api.sh` uses these explicit non-zero codes for contract failures:

- `11`: rewrite response missing `execution_session_id`
- `12`: blocked-policy path did not return expected `403`
- `13`: delivery enqueue response missing `delivery_id`

Other transport failures (for example `curl`) return their native non-zero exit codes.
