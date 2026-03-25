# Experience success metrics

## Purpose

This file translates Chummer's internal scorecards back into user-facing promises.

The product should be steerable as a lived system, not only as a set of repo-local release checks.

Detailed gate truth still lives in:

* `METRICS_AND_SLOS.yaml`
* `PRODUCT_HEALTH_SCORECARD.yaml`

## Build

User promise:

* numbers and legality stay reproducible and inspectable

Primary canon:

* `METRICS_AND_SLOS.yaml` -> `deterministic_rules_truth`

## Explain

User promise:

* every important answer keeps a readable evidence chain

Primary canon:

* `METRICS_AND_SLOS.yaml` -> `deterministic_rules_truth`
* `PRODUCT_HEALTH_SCORECARD.yaml` -> `design_drift`

## Run

User promise:

* the same runner, crew, and session survive reconnect, continuity drift, and replay-driven recovery

Primary canon:

* `METRICS_AND_SLOS.yaml` -> `session_continuity`
* `METRICS_AND_SLOS.yaml` -> `campaign_and_dossier_continuity`
* `PRODUCT_HEALTH_SCORECARD.yaml` -> `campaign_middle_health`

## Publish

User promise:

* finished artifacts stay grounded in manifests, previews, and provenance

Primary canon:

* `METRICS_AND_SLOS.yaml` -> `artifact_publication_integrity`

## Improve

User promise:

* reporting pain is not a dead end
* support status means what it says
* fixes are only called fixed when they reached the user's real channel or closure state

Primary canon:

* `METRICS_AND_SLOS.yaml` -> `support_and_closure_honesty`
* `PRODUCT_HEALTH_SCORECARD.yaml` -> `support_and_feedback_closure`
* `PRODUCT_HEALTH_SCORECARD.yaml` -> `control_loop_integrity`

## Rule

If the product can only prove internal repo progress and cannot explain Build, Explain, Run, Publish, and Improve in user terms, the scorecard layer is incomplete.
