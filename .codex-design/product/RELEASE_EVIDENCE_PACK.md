# Release Evidence Pack

Last reviewed: 2026-07-11

Purpose: close `WL-D037` by keeping the final release argument in one canonical location.
This pack records foundation and wave-closeout truth, but full public-release completeness still depends on the flagship acceptance bar in `FLAGSHIP_RELEASE_ACCEPTANCE.yaml`.

## Program exit summary

- All phase exits from `A` through `F` are materially met in `PROGRAM_MILESTONES.yaml`.
- `GROUP_BLOCKERS.md` reports no red blockers.
- The product vision, horizon canon, public-guide policy, and Fleet participation/support posture are all canonical and downstream-synced from this repo.
- The Account-Aware Front Door wave is materially closed on public `main`; see `ACCOUNT_AWARE_FRONT_DOOR_CLOSEOUT.md` for the post-foundation public-surface closeout record.
- The Next 20 Big Wins wave is also materially closed on public `main`; `NEXT_20_BIG_WINS_EXECUTION_PLAN.md` and `NEXT_20_BIG_WINS_REGISTRY.yaml` now serve as the preserved additive-wave closeout record, while `NEXT_15_BIG_WINS_EXECUTION_PLAN.md` remains the older historical plan.
- The Post-Audit Next 20 Big Wins wave is now materially closed on public `main`; see `POST_AUDIT_NEXT_20_BIG_WINS_CLOSEOUT.md` for the additive follow-on closeout record.
- The active flagship-closeout wave is `NEXT_12_BIGGEST_WINS_GUIDE.md` with machine-readable status in `NEXT_12_BIGGEST_WINS_REGISTRY.yaml`.
- The queued successor wave is `NEXT_90_DAY_PRODUCT_ADVANCE_GUIDE.md` with machine-readable staging in `NEXT_90_DAY_PRODUCT_ADVANCE_REGISTRY.yaml` and `NEXT_90_DAY_QUEUE_STAGING.generated.yaml`.

## Owner-repo evidence

- `chummer6-core`: contract canon, explain/runtime canon, restore/runbook proof, legacy migration certification, and explicit legacy-root quarantine are recorded in `docs/CONTRACT_BOUNDARY_MAP.md`, `docs/EXPLAIN_AND_RUNTIME_CANON.md`, `docs/CORE_RUNTIME_RESTORE_RUNBOOK.md`, `docs/LEGACY_MIGRATION_CERTIFICATION.md`, and `docs/LEGACY_ROOT_SURFACE_INVENTORY.md`.
- `chummer6-ui`: workbench completion and cross-head signoff are explicit in `docs/WORKBENCH_RELEASE_SIGNOFF.md`.
- `chummer6-mobile`: replay, reconnect, installable-PWA, and release hardening are explicit in `docs/PLAY_RELEASE_SIGNOFF.md`.
- `chummer6-hub`: hosted boundary, adapter authority, assistant governance, docs/help, feedback, and operator-consumer posture are explicit in `docs/HOSTED_BOUNDARY.md`, `docs/HOSTED_ADAPTER_AUTHORITY.md`, `docs/ASSISTANT_PLANE_AUTHORITY.md`, `docs/HOSTED_DOCS_HELP_CONSUMERS.md`, and `docs/HOSTED_FEEDBACK_AND_OPERATOR_CONSUMERS.md`.
- `chummer6-ui-kit`: shared package release posture is explicit in `docs/SHARED_SURFACE_SIGNOFF.md`.
- `chummer6-hub-registry`: owner-read-model and restore proof are explicit in `docs/REGISTRY_PRODUCT_READMODELS.md` and `docs/REGISTRY_RESTORE_RUNBOOK.md`.
- `chummer6-media-factory`: adapter authority, stable media capability, and restore proof are explicit in `docs/MEDIA_ADAPTER_MATRIX.md`, `docs/MEDIA_CAPABILITY_SIGNOFF.md`, and `docs/MEDIA_FACTORY_RESTORE_RUNBOOK.md`.
- `fleet`: design remains mirrored into runtime/operator truth, and premium-burst participation is design-first canon before downstream execution.
- `chummer6-design`: weekly pulse publication now emits a generated governor snapshot, interop/portability canon is explicit enough to stop relying on code archaeology, and the next-wave registries are machine-readable rather than prose-only.

## Mirror and truth freshness

- primary executable proof: `bash scripts/ai/verify.sh`
- sync topology proof: `python3 scripts/ai/validate_sync_manifest.py`
- downstream root-canon proof: `python3 scripts/ai/validate_downstream_root_aliases.py`
- local parity proof: `python3 scripts/ai/publish_local_mirrors.py --check`
- historical audit trails remain in `products/chummer/sync/REVIEW_TEMPLATE_MIRROR_PUBLISH_EVIDENCE.md`, `products/chummer/sync/LOCAL_MIRROR_PUBLISH_EVIDENCE.md`, and `products/chummer/maintenance/TRUTH_MAINTENANCE_LOG.md`

## Human-only boundaries

- `HUMAN_ONLY_RELEASE_BOUNDARIES.generated.md` is the canonical product-level handoff for anything automation cannot honestly clear.
- Current verdict: `CLEAR`.
- The source `FULL_PRODUCT_RULE_AUTHORITY_COMPLETION.generated.json` reports `FULL_RULE_AUTHORITY_READY`, so no SR4 or SR6 human-only release boundary remains open for the promoted scope.
- Future authority changes must reopen the generated human-boundary receipt rather than relying on this prose.

## Promotion posture

Chummer foundation release is complete at the canonical product/design level.
The first account-aware install, update, support, and operator-control wave is also materially closed on public `main`.
The Next 20 Big Wins additive wave is materially closed on public `main`.
The post-audit next 20 sequence is materially closed on public `main`.
The active flagship-closeout wave records the final proof priorities after that closeout.
The queued Next 90-Day Product Advance wave records the widened successor priorities after flagship closeout: release truth, parity proof, continuity, artifact factory proof, campaign orientation, campaign operations, rules/build/exchange moat, creator and community publication, onboarding, launch health, and measured product-governor cadence.
The signed-in home cockpit, explicit rule-environment posture, living-dossier runtime object, package-owned campaign-contract adoption, roaming restore packet, Build Lab handoff UX, Rules Navigator, migration receipts, creator publication posture, and the first organizer/operator account surface are now part of the shipped public/account-aware product surface rather than only planned canon.
The weekly pulse itself now emits a bounded generated snapshot, and interop/portability now has explicit canon plus runtime/export proof instead of implied compatibility drift.
Public product maturity is still advancing in broader promotion breadth, estate-wide adoption, live operator cadence, and measured production depth rather than in still-missing repo-local canon or package seams.
That remaining work is additive product growth, not evidence that foundation design or repo-boundary truth is still missing.

## Flagship release rule

This file is not by itself sufficient proof of a flagship-complete public release.

A final flagship release argument must also show:

* `FLAGSHIP_RELEASE_ACCEPTANCE.yaml` pass posture or bounded preview explanations
* journey evidence from `GOLDEN_JOURNEY_RELEASE_GATES.yaml`
* explicit rule-environment and amend-package honesty on build, import, restore, and explain surfaces
* public/download/help/support coherence with the actual promoted artifacts

The current release decision also publishes `CAMPAIGN_OPERABILITY_SCORECARD.generated.json`. It must score all six required surfaces across all six rubric dimensions at `3`; aggregate green tests or an empty support queue cannot substitute for that 36-cell proof.
