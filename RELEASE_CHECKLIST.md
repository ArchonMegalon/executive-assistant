# Release Checklist

## Preflight

- [ ] `git status` is clean on release branch.
- [ ] `.env` is present with production-safe values.
- [ ] `EA_LEDGER_BACKEND=postgres` and `DATABASE_URL` are set.
- [ ] CI smoke workflow is green.

## Build & Deploy

- [ ] `bash scripts/deploy.sh`
- [ ] If first rollout or schema changes pending: `EA_BOOTSTRAP_DB=1 bash scripts/deploy.sh`

## Migrations

- [ ] `bash scripts/db_bootstrap.sh`
- [ ] `bash scripts/db_status.sh`
- [ ] Confirm tables exist:
  - `execution_sessions`
  - `execution_events`
  - `observation_events`
  - `delivery_outbox`
  - `policy_decisions`

## Smoke

- [ ] `bash scripts/smoke_api.sh`
- [ ] Confirm blocked-policy path returns `403`.
- [ ] Confirm `/v1/policy/decisions/recent` includes new entries after rewrite call.

## Observability

- [ ] Check `docker compose logs --tail 200 ea-api ea-db` for errors.
- [ ] Verify no repeated fallback warnings in postgres-required environments.

## Rollback

- [ ] Keep previous image tag available.
- [ ] Re-deploy prior image if smoke fails.
- [ ] Preserve DB data volume; do not drop tables during rollback.
- [ ] Open incident note with failing endpoint, timestamps, and logs.
