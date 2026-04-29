# Product control and governor loop

## Purpose

This file defines Chummer's product-control plane.

The product needs more than:

* repo ownership
* release artifacts
* support inboxes

It needs a governed center that can answer:

* what is hurting users now
* who owns the next action
* whether the product promise is still honest
* when reality should change canon, queue, or release posture

## Control-plane objects

The minimum control plane carries:

* support case
* crash record
* signal packet
* public feedback digest
* public content brief
* decision packet
* health scorecard
* release-readiness fact
* closure notice

## Role split

### Product governor

Owns:

* whole-product pulse
* stop, freeze, reroute, and defer posture
* final routing for cross-repo decision packets
* ProductLift status-change approval when a public item becomes planned or shipped
* Katteb content-priority and publication-approval posture

Detailed operator authority lives in `PRODUCT_GOVERNOR_AND_AUTOPILOT_LOOP.md`.

### `chummer6-hub`

Owns:

* raw intake
* case truth
* reporter-facing closure
* public feedback, roadmap, changelog, and guide/content routes with first-party fallbacks

### `fleet`

Owns:

* clustering
* evidence synthesis
* execution aids
* published support-case packet artifacts that summarize open case clusters for operator and designer pulses
* ProductLift digest and shipped-item closeout evidence synthesis after Hub-owned intake exists

### `chummer6-design`

Owns:

* canon changes
* boundary changes
* milestone and blocker truth
* ProductLift taxonomy, public signal policy, and Katteb source-truth boundaries

### `executive-assistant`

Owns:

* governed synthesis aids and packet preparation downstream of canon
* public feedback digest normalization and Katteb source brief preparation

## Contract family

The initial shared DTO family is `Chummer.Control.Contracts`.

It should carry:

* support and crash intake DTOs
* case status and closure notices
* clustered signal packets
* public feedback digest refs
* public content brief refs
* decision packet refs
* product-health and release-readiness projections

## Detailed sub-docs

This control-plane layer compiles into:

* `SUPPORT_AND_SIGNAL_OODA_LOOP.md` for support and signal flow
* `FEEDBACK_AND_CRASH_REPORTING_SYSTEM.md` for intake lanes
* `FEEDBACK_AND_SIGNAL_OODA_LOOP.md` for packet routing detail
* `FEEDBACK_AND_CRASH_STATUS_MODEL.md` for case status semantics
* `PRODUCT_GOVERNOR_AND_AUTOPILOT_LOOP.md` for operator authority
* `PRODUCT_HEALTH_SCORECARD.yaml` for weekly pulse
* `PUBLIC_SIGNAL_TO_CANON_PIPELINE.md` for public signal and content optimization routing
* `PRODUCTLIFT_FEEDBACK_ROADMAP_BRIDGE.md` and `KATTEB_PUBLIC_GUIDE_OPTIMIZATION_LANE.md` for bounded external public-surface posture

## Non-goals

This file does not:

* make Hub the product governor
* make Fleet canonical product truth
* turn support notes into direct roadmap authority
* turn ProductLift votes into direct roadmap authority
* turn Katteb content suggestions into guide truth without upstream source changes
* replace the detailed support, packet, or status docs
