# Release Checklist

## Preflight

- [ ] `git status` is clean on release branch.
- [ ] `.env` is present with production-safe values.
- [ ] `EA_STORAGE_BACKEND=postgres` and `DATABASE_URL` are set.
- [ ] Product boundary reviewed: non-core public utility routes are disabled unless intentionally required (`EA_ENABLE_PUBLIC_RESULTS`, `EA_ENABLE_PUBLIC_TOURS`).
- [ ] CI smoke workflow is green.
- [ ] CI gate bundle (`make smoke-help`, `make ci-local`, runtime smoke API tests, `make verify-release-assets`) is green.
- [ ] Optional local parity run completed: `make ci-gates`.
- [ ] Optional local parity run including Postgres smoke completed: `make ci-gates-postgres`.
- [ ] Optional local parity run including legacy migration smoke completed: `make ci-gates-postgres-legacy`.
- [ ] Optional docs parity run completed: `make docs-verify`.
- [ ] Optional docs+usage parity run completed: `make release-docs`.
- [ ] Docs parity confirms milestone release tags in `MILESTONE.json` (`ci_gate_bundle`, `release_preflight_bundle`, `docs_verify_alias`).

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

- [ ] Optional one-command release bundle: `make release-preflight`
- [ ] `make release-smoke`
- [ ] Browser surface contract tests confirm no product-surface links to experimental routes in product mode.
- [ ] `make operator-help` (manual spot-check of script usage contracts)
- [ ] Optional combined local mirror: `make ci-gates`
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
