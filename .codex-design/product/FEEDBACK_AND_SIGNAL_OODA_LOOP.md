# Feedback and signal OODA loop

## Purpose

This file defines how Chummer turns raw signals into governed product action.
It is the packet-routing detail underneath `SUPPORT_AND_SIGNAL_OODA_LOOP.md`.

The goal is not a giant inbox.
The goal is a closed loop:

* observe real product pain
* orient it against release and canon truth
* decide the right lane
* act and close the loop back to the user

## Signal classes

The first canonical signal families are:

* crash
* structured bug
* lightweight feedback
* survey result
* public issue
* Discord or community signal
* release regression
* release smoke-start failure
* blocker drift
* public-promise drift

Public signals remain advisory.
They do not become canon or priority truth on arrival.

## Observe

### Hub intake

Hub owns the raw inbox for:

* crash reports
* support cases
* linked-install follow-up
* survey invites and responses
* user-visible closure

### Fleet clustering

Fleet owns:

* dedupe
* clustering
* evidence packets
* support-case packet artifacts for operator and designer review
* repro or routing aids
* grouped candidate actions

### Fleet release verification

Fleet also owns the machine-generated release signal plane for:

* cross-platform build receipts
* startup smoke receipts
* smoke-start crashes or failed-ready startup receipts from controlled verification hosts

### Signal packet rule

Raw signals must become one bounded packet before they influence roadmap or queue truth.

A packet should contain:

* signal family
* audience or affected users
* severity
* recurrence or breadth
* affected release/channel/build where known
* linked support or crash clusters
* likely owner repos
* recommended routing lane
* verification-host and startup-phase facts when the signal is a release smoke-start failure

## Orient

Packets are classified along these axes:

* user pain
* trust impact
* release impact
* audience
* scope breadth
* design contradiction
* public-promise drift

### Design-impact criteria

Send a packet to the lead designer when any of these are true:

* the issue exposes missing or contradictory canon
* multiple repos are inventing local truth around the same seam
* the public story no longer matches product or release reality
* the packet implies a boundary or package change

### Product-governor criteria

Send a packet to the product governor when any of these are true:

* the issue crosses repo boundaries
* the issue threatens release readiness or user trust
* the right fix lane is ambiguous
* freeze, reroute, or defer posture is required
* a platform head built but failed startup smoke before promotion

## Decide

The legal routing outcomes are:

* code fix
* docs/help fix
* queue/package fix
* support knowledge or closure fix
* policy update
* canon update
* release freeze or rollback
* defer or reject with explicit rationale

### Packet-to-action rule

Every accepted packet must point at one concrete next owner:

* `chummer6-ui`
* `chummer6-hub`
* `chummer6-hub-registry`
* `fleet`
* `chummer6-design`
* another named owning repo

## Act

### Designer role

The lead designer is not the raw inbox.
The designer consumes already-clustered packets that carry:

* evidence
* contradiction summary
* affected canon files
* recommended change class

### Product governor role

The product governor decides whether the packet becomes:

* code
* docs
* queue
* policy
* canon
* release action

### Hub closure

Hub closes the loop back to the user when appropriate through:

* case-status updates
* known-issue linkage
* fix-available notices
* follow-up surveys

## Closure rule

The loop is not closed when:

* a packet was merely clustered
* a PR merged
* a design note was drafted

The loop is closed only when:

* the chosen action actually landed
* the reporter-facing status was updated where appropriate
* public help or release truth was corrected when needed

## Release-gate tie-in

The flagship release loop must measure this through `FEEDBACK_LOOP_RELEASE_GATE.yaml`.

That gate is allowed to fail flagship truth when any of these are still open:

* non-external packets still lack a named owner or next lane
* closure is waiting on release truth
* update-required cases are misrouted away from downloads or updater recovery
* the support packet surface is stale or cached
* an external-host proof backlog exists without a synced runbook
* the staged `request_received -> audited_decision -> fix_available` email loop is missing, underspecified, or not bound to sent receipts

## Forbidden shortcuts

The loop must not:

* treat the feedback folder as canonical product truth
* turn public votes into direct roadmap authority
* make the designer the first-line support inbox
* let Fleet become the support-case database
* skip evidence synthesis and publish one queue task per raw complaint
