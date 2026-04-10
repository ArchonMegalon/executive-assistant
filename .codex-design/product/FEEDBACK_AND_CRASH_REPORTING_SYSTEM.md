# Feedback and crash reporting system

## Purpose

This file defines the first real Chummer support plane for:

* crash reporting
* structured bug reporting
* lightweight product feedback
* knowledge and recovery guidance

without letting a support assistant, a help-desk vendor, or an owned LTD become canonical product truth.

Crash-intake automation, Fleet consumption rules, and the release/review boundary for automated crash triage are defined in `FEEDBACK_AND_CRASH_AUTOMATION.md`.
Signal clustering, routing, and closure discipline beyond raw intake are defined in `FEEDBACK_AND_SIGNAL_OODA_LOOP.md`.

## Non-goals

This file does not define:

* a chat support assistant as the first support feature
* a requirement to buy another AppSumo LTD for the core crash path
* a rule that private diagnostics must be pushed into a public issue tracker
* raw desktop clients sending crash payloads straight to Fleet as the primary seam
* Fleet hot-patching production because one crash report arrived
* Fleet, Hub Registry, or a vendor dashboard as the support-ticket system of record
* a permanent commitment to one support vendor
* reuse of `Karma Forge` as a support or chat-assistant product name

## Canonical terms

### Crash report

An intake record for unexpected termination, hard failure, or next-launch recovery after a crash.
Crash reports are private by default because logs, traces, and dumps may contain sensitive data.

### Bug report

A structured report for reproducible behavior with expected-versus-actual detail, repro steps, optional screenshot evidence, and optional diagnostics attachments.

### Feedback

A low-friction "something feels off", "this is confusing", or "please build this" signal with minimal mandatory fields.

### Diagnostics bundle

A user-reviewable attachment bundle created by the client.
It defaults to redacted and safe metadata.
Full diagnostics remain explicit opt-in.
Crash-triggered temporary debug uplift may still exist as a narrow recovery exception, but the next-launch recovery UI must offer an opt-out and remember if the user declines future crash-triggered debug capture.

### Support case

A Hub-owned hosted ticket/thread record that may absorb a crash report, bug report, or feedback item and later link to knowledge articles, public issues, or human escalation.

### Claimed install

A desktop installation linked to a Hub account after download or first launch.
Claimed installs let support history, fix notices, and gated-channel guidance attach to one real local copy without turning the installer into a per-user artifact.

### Support assistant

A later optional Hub-side helper that answers from curated help, known-issue, and support-case sources.
It is not phase 0 and it does not replace the crash, bug, or feedback lanes.

## First implementation order

1. crash reporting
2. structured bug reporting
3. lightweight feedback
4. knowledge base and human escalation
5. assistant later

That order is intentional.
The support plane must work before any support assistant becomes user-facing.

## Three-lane support plane

### Lane 1 - Crash report

The crash lane is for "Chummer closed unexpectedly" and similar failures.

Phase-1 expectations:

* local interception of managed unexpected-failure paths where possible
* next-launch recovery dialog
* crash-triggered temporary debug uplift may be auto-armed for the immediate reopen, but the recovery dialog must offer a remembered opt-out
* private send/review/don't-send choice
* redacted diagnostics bundle creation
* offline spool and retry when transport is unavailable
* no dependency on chat, sign-in, or a vendor widget
* claimed-install linkage as an optional later enhancement, not a prerequisite for public stable crash reporting

### Lane 2 - Bug report

The bug lane is for reproducible issues.

Phase-1 expectations:

* expected versus actual
* repro steps
* optional screenshot
* optional diagnostics attachment
* auto-filled build, platform, channel, and version facts
* clean split between public-safe issue filing and private Hub intake
* every user-facing bug/help/contact route must resolve to a public, externally routable host rather than an internal Docker, cluster-local, or service-discovery hostname

### Lane 3 - Feedback

The feedback lane is for low-friction product signals.

Phase-1 expectations:

* very low form burden
* support for "idea", "confusing", and "something feels off" style input
* clustering and triage later without pretending the first submission is already a ticket

## Public versus private rule

Public-safe reproducible bugs and guide/help feedback may still flow to the public issue lane.

Private or potentially sensitive material must stay out of the public issue lane by default, especially:

* crash diagnostics
* account-specific cases
* local file-path or environment disclosures
* logs or traces with user content

The support plane must make that split obvious to normal users.

## Public-route safety rule

User-visible support, feedback, bug, crash, and contact handoffs must resolve to:

* the public Chummer host
* or an in-app local dialog that never exposes transport details

They must not resolve to:

* Docker hostnames such as `chummer-api`
* cluster-local service names
* internal ports
* operator-only HTTP origins

If the public route is unavailable, the product must keep the action in-shell or mark it unavailable with honest guidance. It must not leak an internal fallback URL into the user experience.

## Crash automation rule

Automatic forwarding for triage is allowed, but the boundary stays clean:

1. `chummer6-ui` captures the crash locally and sends a redacted crash envelope to a Hub-owned intake endpoint.
2. `chummer6-hub` stores the support/case truth and normalizes that intake into crash work.
3. `chummer6-hub-registry` enriches the incident with version, channel, platform, arch, release-head, runtime-bundle-head, and update facts.
4. `fleet` may consume the normalized crash work item for clustering, repro, test generation, candidate patch drafting, and PR preparation.

That does not make Fleet the support database, and it does not allow direct client-to-Fleet raw crash transport as the primary seam.
Any user-visible repair still ships through the standard review, release, registry, and updater path.

## Crash-triggered debug uplift rule

Crash-focused debug uplift is not general always-on telemetry.

The rule is:

1. full diagnostics and manual debug uplift remain explicit opt-in
2. after a crash, the crash handler may temporarily arm a crash-debug window for the immediate recovery reopen
3. the recovery UI must say that this happened because Chummer crashed
4. the user must get one clear opt-out that disables future crash-triggered debug uplift and remembers that decision
5. declining crash-triggered debug uplift must not block crash reporting, recovery guidance, or the ability to reopen and continue

## Canonical split

### `chummer6-design`

Owns:

* support-plane policy
* state model
* privacy/default-redaction rules
* package and contract-family placement
* sequencing and non-goal boundaries

Must not own:

* crash SDK code
* help-desk adapters
* desktop or browser entrypoint code

### `chummer6-ui`

Owns:

* in-app feedback, bug-report, and crash-report entry points
* local crash interception where the client can catch it
* redacted diagnostics bundle creation
* offline spool and retry behavior
* redacted crash-envelope forwarding to Hub-owned intake
* next-launch "Chummer closed unexpectedly" recovery UX
* local recovery/help affordances that do not require hosted chat

Must not own:

* hosted support-ticket truth
* knowledge-base truth
* support-assistant orchestration
* canonical release or update truth

### `chummer6-hub`

Owns:

* support intake APIs and case/thread truth
* crash-intake normalization and orchestration into machine work
* knowledge/help surfaces
* known-issue presentation
* survey bridges
* human escalation flows
* later grounded support-assistant or human-handoff layers

Must not own:

* client-side crash interception
* local diagnostics bundle creation
* canonical release/update truth
* vendor-side support truth as a replacement for Chummer-owned cases

### `fleet`

Owns:

* dedupe, routing, alerting, and triage automation around support signals
* crash clustering, repro automation, regression-test drafting, candidate patch drafting, and PR preparation from normalized crash work items
* operator-facing clustering and escalation aids

Must not own:

* support-ticket truth
* raw desktop client crash intake as the primary seam
* the primary user-facing crash path
* canonical help/article truth
* merge or release authority that bypasses the normal review/update path

### `chummer6-hub-registry`

Owns:

* release/install/update truth
* version, channel, platform, arch, runtime-bundle-head, and update-availability facts that support cases and crash incidents may read for enrichment

Must not own:

* support cases
* bug-report truth
* crash-report truth
* help-desk orchestration

Support surfaces may read release, platform, version, channel, and update-availability facts from registry truth so cases stay version-aware without inventing a second release record.

## Install-linking rule

Support cases may link to either:

* a guest installation identity
* or a claimed installation tied to a Hub account

That improves closure and notification without requiring per-user binaries or sign-in-gated public downloads.

## Contract placement rule

Support intake and case/thread DTOs belong in `Chummer.Control.Contracts`, not in UI-local DTO families and not in registry contracts.

The minimum first-wave family is:

* crash envelope intake
* diagnostics attachment references
* bug report submission
* feedback submission
* support case/thread state
* knowledge-article and public-issue links
* crash cluster projections
* crash work items for downstream triage automation

## Default metadata rule

The default safe attachment/report metadata is:

* app version
* release channel
* platform
* arch
* desktop head and runtime head where known
* last screen or action category where known
* recent redacted log excerpts
* update availability facts where known

Full diagnostics remain opt-in.

## Assistant rule

Now that the first support plane is real, the grounded assistant may exist only as the later phase-2 layer. It must:

* live on Hub/help-center surfaces first
* answer from curated help, known-issue, and support-case sources
* hand off cleanly to human support when confidence is low
* remain optional rather than gating crash or bug submission

The assistant remains phase 2.
It is not the first support feature and it is not the system of record.

## External-tool and LTD rule

External tools may assist with:

* docs/help projection
* structured feedback collection
* support/help-desk routing
* knowledge search

They must not become:

* the canonical crash path
* the only support-case system of record
* the gate in front of bug or crash submission

Owning or discovering another AppSumo LTD does not change the first-wave requirement.
Chummer does not need another AppSumo LTD to ship the core crash path.

## Naming rule

`Karma Forge` already means ruleset-variation/build-axis canon.
It must not be reused as the name of the first support assistant or support plane.
