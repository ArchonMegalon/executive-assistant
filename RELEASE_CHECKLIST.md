# Release Checklist

## Manfred qualification permit — hard stop

Complete this section before any Manfred candidate image/runtime, memorial
preflight, or live deploy command below. `enforced_soak`, a non-terminal state,
a missing/untrusted permit or lock, unhealthy current resources, or any
certification blocker means stop; none of the later Manfred commands are
authorized.

- [ ] The schema-v6 sentinel is terminal `qualified`, its required completion time has elapsed, current resources are healthy, and `certification_blockers` is empty.
- [ ] A root operator materialized the manager from the exact reviewed Git commit and reviewed blob digest, then installed it root:root mode `0555` at `/usr/local/libexec/ea/manage-manfred-vexp-mutation-permit`; no checkout Python was executed as root.
- [ ] Every manager command used `/usr/bin/python3 -I` under sanitized `env -i`; `issue` and `status` received the explicit absolute state path and numeric state-owner UID, and no permit JSON was created or edited by hand.
- [ ] State-bound `status` passed immediately before candidate image/runtime creation; the accepted image, source revision, public projection, and priority 3D-tour receipts all match.
- [ ] Candidate creation and exact-tour proof passed before production preflight.
- [ ] `python3 scripts/deploy_ea_memorial.py --preflight-only` passed without a mutation claim.
- [ ] The root operator refreshed the short-lived permit immediately before promotion, and state-bound `status` passed again immediately before deploy.
- [ ] Promotion used only `python3 scripts/deploy_ea_memorial.py`; no raw Docker or broad EA deploy bypass was used.
- [ ] The exact revision passed credential-free public proof for `/memorials/manfred`, `/memorials/manfred.json`, and the configured priority `/tours/...` HTML/JSON route.
- [ ] The root operator revoked the permit after proof; a busy lock was retried only after the bounded governed mutation completed.

## Preflight

- [ ] Release source is committed on an attached branch with a real upstream; never deploy from detached `HEAD`. For an isolated release, create an attached temporary worktree branch and set its upstream before materializing authority.
- [ ] Source worktree is clean before preflight. Paths classified as generated-only by `source_state_head` may change during preflight, but any source-dirty entry remains a hard deploy failure.
- [ ] `.env` is present with production-safe values.
- [ ] `EA_STORAGE_BACKEND=postgres` and `DATABASE_URL` are set.
- [ ] `PRODUCT_RELEASE_CHECKLIST.md` is fully satisfied for the current product wedge.
- [ ] `FLAGSHIP_CLOSEOUT_PLAN.md` blocker set is green enough to support the intended release claim.
- [ ] `.codex-design/ea/START_HERE.md` and the linked EA canon docs still match the shipped public/app surface.
- [ ] `EA_FLAGSHIP_TRUTH_PLANE.md`, `EA_FLAGSHIP_RELEASE_GATE.json`, and `EA_FLAGSHIP_RELEASE_GATE.generated.json` agree with the browser workflow proof.
- [ ] `make verify-release-authority` passes, confirming the release manifest points at a real runtime origin, carries an explicit deployment id, records compose topology, and is not being claimed from a dirty local worktree.
- [ ] `curl -fsS http://localhost:${EA_HOST_PORT:-8090}/health/release-authority` returns the deployed release-authority posture and gate payload expected for this rollout.
- [ ] `make verify-flagship-release-readiness` passes, confirming the weekly pulse, browser proof, flagship receipt, and Fleet journey gate are all clear for wider release claims.
- [ ] `make verify-whole-project-gold-map` passes, confirming EA readiness is not being overclaimed as whole-Chummer gold and that memorial voice/realtime remains separately blocked until its own receipt exists.
- [ ] Product boundary reviewed: non-core public utility routes are disabled unless intentionally required (`EA_ENABLE_PUBLIC_RESULTS`, `EA_ENABLE_PUBLIC_TOURS`).
- [ ] Local release gate bundle is green (`make ci-gates`, `make release-preflight`, and any required Postgres parity run).
- [ ] CI gate bundle (`make smoke-help`, `make ci-local`, runtime smoke API tests, `make verify-release-assets`) is green.
- [ ] Optional local parity run completed: `make ci-gates`.
- [ ] Optional local parity run including Postgres smoke completed: `make ci-gates-postgres`.
- [ ] Optional local parity run including legacy migration smoke completed: `make ci-gates-postgres-legacy`.
- [ ] Optional docs parity run completed: `make docs-verify`.
- [ ] Optional docs+usage parity run completed: `make release-docs`.
- [ ] Docs parity confirms the EA canon, flagship truth plane, gate seed, and generated receipt are present and the browser proof is still green.

## Build & Deploy

- [ ] `bash scripts/deploy.sh`
- [ ] If first rollout or schema changes pending: `EA_BOOTSTRAP_DB=1 bash scripts/deploy.sh`
- [ ] For the Manfred public memorial, use the API-only governed lane in `docs/MANFRED_MEMORIAL_SCOPED_DEPLOY_RUNBOOK.md`; do not use the mega-stack deployer to publish only the memorial.
- [ ] Memorial deployment has a unique explicit `EA_DEPLOYMENT_ID`, an immutable revision-bound `EA_MEMORIAL_IMAGE`, a clean tracking release branch, a durable release root, and a private rollback receipt.
- [ ] Memorial preflight proves the captured prior Compose topology still renders to the live API image, normalized environment/process identity, and mount digest under the stripped rollback environment.
- [ ] `EA_MEMORIAL_CANDIDATE_RECEIPT` is a mode-`0600` passing runtime-v4 receipt bound to the exact image/revision, immutable memorial projection root/digest, isolated project/port locks, and `EA_MEMORIAL_DATA_HOST_PATH`; its browser audit has zero provider work, WebSockets, failed requests, page errors, external requests, and same-origin HTTP errors.
- [ ] `EA_MEMORIAL_CONTROL_TOUR_SLUG` is set for any priority 3D tour that must survive promotion; OpenAPI remains a path superset and the tour's pre/post JSON digest is identical.

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

- [ ] Optional one-command release bundle: `make release-preflight` (includes runtime supply-chain, release-authority, and flagship release-readiness verification)
- [ ] `make release-smoke`
- [ ] The core workspace proves one real memo -> queue -> draft/approval -> follow-up loop on durable product objects.
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
