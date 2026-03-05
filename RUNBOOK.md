# Runtime Runbook

## 1) Start Services

```bash
bash scripts/deploy.sh
```

With schema bootstrap in one step:

```bash
EA_BOOTSTRAP_DB=1 bash scripts/deploy.sh
```

## 2) Apply Kernel Migrations Manually

```bash
bash scripts/db_bootstrap.sh
```

Applies:
- `ea/schema/20260305_v0_2_execution_ledger_kernel.sql`
- `ea/schema/20260305_v0_3_channel_runtime_kernel.sql`
- `ea/schema/20260305_v0_4_policy_decisions_kernel.sql`

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
