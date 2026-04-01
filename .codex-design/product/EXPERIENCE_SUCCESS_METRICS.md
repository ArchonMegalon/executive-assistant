# Experience success metrics

## Purpose

This file translates Chummer's internal scorecards back into user-facing promises.

The product should be steerable as a lived system, not only as a set of repo-local release checks.

Detailed gate truth still lives in:

* `METRICS_AND_SLOS.yaml`
* `PRODUCT_HEALTH_SCORECARD.yaml`
* `FLAGSHIP_RELEASE_ACCEPTANCE.yaml`

Flagship release posture adds three cross-cut expectations:

* the primary path for each major job is obvious
* the path feels authored for the active ruleset or role instead of flattened into lowest-common-denominator UX
* trust, recovery, and public-facing guidance stay coherent before, during, and after failure

## Build

User promise:

* numbers and legality stay reproducible and inspectable
* the fastest builder path still feels crafted for edition-specific reasoning and dense expert work

Primary canon:

* `METRICS_AND_SLOS.yaml` -> `deterministic_rules_truth`

## Explain

User promise:

* every important answer keeps a readable evidence chain
* explain surfaces stay understandable to a paying user, not only to a debugger

Primary canon:

* `METRICS_AND_SLOS.yaml` -> `deterministic_rules_truth`
* `PRODUCT_HEALTH_SCORECARD.yaml` -> `design_drift`

## Run

User promise:

* the same runner, crew, campaign, and recent workspace survive claimed-device handoff, reconnect, continuity drift, and replay-driven recovery
* live-play shells clearly distinguish what is safe, stale, pending, or conflicted

Primary canon:

* `CAMPAIGN_WORKSPACE_AND_DEVICE_ROLES.md`
* `METRICS_AND_SLOS.yaml` -> `session_continuity`
* `METRICS_AND_SLOS.yaml` -> `campaign_and_dossier_continuity`
* `METRICS_AND_SLOS.yaml` -> `roaming_workspace_trust`
* `PRODUCT_HEALTH_SCORECARD.yaml` -> `campaign_middle_health`

## Publish

User promise:

* finished artifacts stay grounded in manifests, previews, and provenance
* public-facing artifacts look deliberate enough to share without apology

Primary canon:

* `METRICS_AND_SLOS.yaml` -> `artifact_publication_integrity`

## Improve

User promise:

* reporting pain is not a dead end
* support status means what it says
* fixes are only called fixed when they reached the user's real channel or closure state
* downloads, status, help, support, and in-product messaging never disagree about the user's next safe action

Primary canon:

* `METRICS_AND_SLOS.yaml` -> `support_and_closure_honesty`
* `PRODUCT_HEALTH_SCORECARD.yaml` -> `support_and_feedback_closure`
* `PRODUCT_HEALTH_SCORECARD.yaml` -> `control_loop_integrity`

## Rule

If the product can only prove internal repo progress and cannot explain Build, Explain, Run, Publish, and Improve in user terms, the scorecard layer is incomplete.
If it can describe those promises but cannot tie them back to `FLAGSHIP_RELEASE_ACCEPTANCE.yaml`, the flagship release story is still incomplete.
