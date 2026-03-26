# Provider and route stewardship

## Purpose

This file defines the governed loop for external reasoning-provider and model-route changes.

The goal is not "try new models whenever a vendor announcement lands."
The goal is to keep provider posture boring, evidence-backed, kill-switchable, and lane-specific.

This document sits underneath:

* `EXTERNAL_TOOLS_PLANE.md`
* `PRODUCT_GOVERNOR_AND_AUTOPILOT_LOOP.md`
* `projects/executive-assistant.md`
* `projects/fleet.md`

## Ownership split

### EA runtime steward

Owns:

* provider catalog watch
* lifecycle notice watch
* challenger brief generation
* provider/runtime telemetry
* lane-level cost, latency, fallback, timeout, and retry evidence

Does not own:

* canonical product meaning
* public-trust copy
* final default-route approval

### Hub route owner

Owns:

* lane-to-provider and lane-to-model route maps
* default settings for hosted reasoning lanes
* prompt/schema compatibility checks for hosted routes
* fallback posture for user-facing and support-facing lanes

Does not own:

* provider-secret ownership outside its allowed boundary
* canonical support-case truth
* product-governor freeze authority

### Fleet

Owns:

* eval execution
* canary rollout plans
* rollback plans
* evidence packets for promotion, defer, or rejection

Does not own:

* direct route-canon truth
* ad hoc default flips outside the governed loop

### Product governor

Owns:

* approval for default changes that affect reliability, cost posture, support burden, or public trust
* freeze, reroute, or rollback decisions when a route swap causes measurable product harm

## Lane posture rules

### Easy lanes

Easy lanes optimize for:

* low cost
* low latency
* acceptable structured reliability
* safe fallback behavior

They may use cheaper challenger routes sooner, but still require bounded canary evidence before default promotion.

### Hard coding and high-trust lanes

Hard lanes optimize for:

* stable high-capability reasoning
* coding/tool reliability
* predictable schema behavior
* supportable lifecycle posture

Preview, pre-GA, or unstable models may run as challenger or canary routes.
They must not become the hard-lane default without explicit governor approval and a documented rollback target.

## Required stewardship loop

### 1. Weekly provider scan

The runtime steward checks:

* new candidate models
* lifecycle notices
* retirement risk
* blocked-new-access notices
* pricing, latency, or quota shifts

### 2. Lane-specific benchmark run

Every challenger must be evaluated by lane, not by generic "best model" folklore.

Minimum lane buckets:

* cheap drafting and triage
* tool-heavy coding
* long-context synthesis
* support classification and closure aids

### 3. Canary before default

Every default-route change requires:

* bounded canary or shadow traffic
* success criteria
* rollback target
* stop condition

### 4. Publish the reason

Every lane default must have a bounded registry entry containing:

* current default
* current fallback
* active challenger
* review date
* reason for current default
* rollback target
* next review date

## Required scorecard inputs

Every route review must inspect:

* cost by lane
* latency by lane
* timeout rate
* retry rate
* fallback frequency
* schema or tool-contract break rate
* support-case fallout
* bad-patch or bad-summary regressions where applicable

## Hygiene checklist

The standing checklist is:

* lifecycle hygiene
* prompt and schema hygiene
* cost and quota hygiene
* fallback and rollback hygiene
* secret and access hygiene
* PII and retention hygiene
* eval-corpus hygiene
* mirror and canon drift hygiene
* support-closure hygiene

## Hard rules

* No provider or model swap may bypass adapters, receipts, or kill switches.
* No client repo may become a direct provider-routing authority.
* No route default may be justified only by vendor marketing or announcement velocity.
* If a route swap increases support pain, trust drift, or fix fallout, the governor may revert it immediately.

## Non-goals

This file does not:

* make `executive-assistant` the canonical owner of product truth
* allow Fleet to flip production defaults without route-owner and governor review
* treat preview-model novelty as production-readiness proof
