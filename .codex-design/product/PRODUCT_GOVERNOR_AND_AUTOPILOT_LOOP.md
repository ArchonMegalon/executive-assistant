# Product governor and autopilot loop

## Purpose

This file defines the missing whole-product operator role for Chummer.
It is the operator-role detail underneath `PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md`.

The product governor does not replace the lead designer.
The product governor sits between reality and canon:

* whole-product health
* scope pressure
* support and feedback closure
* release-readiness posture
* stop, freeze, reroute, and replan authority when reality diverges from the current path

The loop stays grounded by a simple rule:

> design truth is not enough; product reality must compile into governed course correction.

## Role split

### Lead designer

Owns:

* canonical product vision
* repo and package boundaries
* milestone and blocker truth
* public-story and horizon canon

Does not own:

* day-to-day stop or reroute calls from live health signals
* support-case closure operations
* the runtime execution plane

### Product governor

Owns:

* whole-product pulse
* release readiness across repos
* cross-repo scope pressure and promise drift review
* stop, freeze, reroute, and escalation decisions when reality contradicts plan
* weekly program pulse using `PRODUCT_HEALTH_SCORECARD.yaml`
* final routing of clustered support and feedback packets into code, docs, queue, policy, or canon changes

Does not own:

* raw support-case truth
* worker execution mechanics
* package canon
* public support closure messaging

### Hub

Owns:

* raw support, crash, survey, and feedback intake
* user/account/install linkage
* case closure and user-facing follow-up

### Fleet

Owns:

* evidence clustering
* feedback and crash packet synthesis
* queue and package proposals
* grounded audit/jury execution aids

### Standing provider and route stewardship

Provider and model defaults are not ad hoc operator taste.
They follow `PROVIDER_AND_ROUTE_STEWARDSHIP.md`.

That means:

* EA produces challenger briefs and runtime telemetry
* Hub owns lane-route maps and default settings
* Fleet runs evals, canaries, and rollback packets
* the product governor approves default changes that materially affect reliability, cost posture, support burden, or public trust

### Groundwork and jury worker lane

The machine counterpart to the product governor is not "more coding workers."
It is a bounded analysis lane:

* groundwork gathers evidence and prepares packets
* jury validates publishability and landing safety
* coding lanes execute only after the packet is clear enough to act

## Autopilot loop

Canonical meaning for the loop lives in design canon.
The live operator implementation lives in Fleet:

* design defines signal meaning, authority, freeze/reroute rules, and allowed actions
* Fleet owns the durable runtime loop, traces, evals, canaries, packets, dashboards, and operator evidence
* Hub owns the user, install, community, and support/control truth those loops read or update
* shell sessions may start or inspect the loop, but they are entrypoints only and not the durable control plane

The closed loop is:

1. Observe
2. Orient
3. Decide
4. Act

### Observe

The governor consumes:

* release health
* crash and support clusters
* feedback clusters
* blocker age
* design-drift findings
* public-promise drift
* queue stagnation
* participant and capacity incidents

### Orient

Every packet must answer:

* who is hurt
* how often
* which release/channel/build is affected
* whether the issue is a code defect, docs gap, queue problem, policy gap, or canon contradiction
* whether the issue threatens public trust, release safety, or roadmap honesty

### Decide

The product governor may choose:

* local code fix
* docs/help fix
* queue/package reroute
* policy adjustment
* design-canon patch
* release freeze or rollback
* defer with explicit rationale

### Act

Actions must publish into one of:

* repo work
* Hub help/support change
* Fleet queue or package change
* design canon update
* release-governance decision

## Freeze and reroute authority

The product governor may freeze or reroute work when any of these are true:

* release health contradicts public claims
* crash or support volume shows a trust-breaking regression
* blocker age or queue churn shows the current plan is no longer credible
* repeated feedback packets identify one unresolved design contradiction
* a public promise now depends on policy or docs that do not exist in canon

The governor must not freeze work casually.
Every freeze or reroute needs:

* one written reason
* one exit condition
* one named downstream action

## Weekly program pulse

The minimum weekly pulse publishes:

* release-health status
* open blocker age posture
* support and feedback closure posture
* provider-route stewardship and canary posture
* measured adoption health and history summary
* launch and expansion posture for the active trail
* design-drift count
* public-promise drift count
* progress trend direction and delta
* top freeze or reroute decisions
* the next checkpoint question

The scorecard source is `PRODUCT_HEALTH_SCORECARD.yaml`.

## Non-goals

This file does not:

* turn Fleet into canonical product truth
* turn Hub into the program governor
* make the lead designer the support inbox
* let raw feedback bypass evidence clustering
* let one support case force a design change without synthesis
