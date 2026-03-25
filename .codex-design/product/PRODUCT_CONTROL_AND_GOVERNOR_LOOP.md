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

Detailed operator authority lives in `PRODUCT_GOVERNOR_AND_AUTOPILOT_LOOP.md`.

### `chummer6-hub`

Owns:

* raw intake
* case truth
* reporter-facing closure

### `fleet`

Owns:

* clustering
* evidence synthesis
* execution aids
* published support-case packet artifacts that summarize open case clusters for operator and designer pulses

### `chummer6-design`

Owns:

* canon changes
* boundary changes
* milestone and blocker truth

### `executive-assistant`

Owns:

* governed synthesis aids and packet preparation downstream of canon

## Contract family

The initial shared DTO family is `Chummer.Control.Contracts`.

It should carry:

* support and crash intake DTOs
* case status and closure notices
* clustered signal packets
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

## Non-goals

This file does not:

* make Hub the product governor
* make Fleet canonical product truth
* turn support notes into direct roadmap authority
* replace the detailed support, packet, or status docs
