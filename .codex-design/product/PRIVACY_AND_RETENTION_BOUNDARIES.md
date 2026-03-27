# Privacy and retention boundaries

## Purpose

This file defines the default privacy, retention, and redaction rules for the campaign OS control plane.

It exists so support, crash, install-linking, survey, assistant, and provider traces do not silently turn into an ungoverned data lake.

## Default rules

* retain the smallest surface that still allows honest closure, replay-safe support, and bounded auditability
* keep install-local secrets, raw auth tokens, updater rollback payloads, and local caches on the install unless canon explicitly promotes them
* prefer structured summaries, receipts, and bounded projections over indefinite raw payload retention
* provider-facing traces must be redacted before persistence unless the owning surface explicitly declares otherwise
* every retained surface needs an owner, a retention clock, a redaction posture, and a delete-or-summarize rule

## Retention domains

### Support-case truth

Owner: `chummer6-hub`

Retention posture:

* case timeline and user-visible status events: retain for 18 months after the last state change
* public known-issue linkage and closure receipts: retain for 18 months after public closure
* raw attachments that are no longer needed for open investigation: summarize or redact within 90 days

Redaction baseline:

* remove secrets, local paths, and unrelated identity data from user-visible case history
* preserve bounded install/channel/version truth needed for honest fix-availability notices

### Crash envelopes

Owner: `chummer6-hub`

Retention posture:

* raw crash envelopes: retain for 90 days unless tied to an active blocker or open case cluster
* normalized crash signatures and clustered receipts: retain for 18 months
* local crash dumps remain install-local unless explicit user action uploads them

Redaction baseline:

* no raw secrets, tokens, or local machine credentials in retained crash payloads
* strip or hash install-local absolute paths when they are not required for a live investigation

### Claim and install linkage

Owner: `chummer6-hub` plus `chummer6-hub-registry`

Retention posture:

* claim tickets and install-link events: retain for 365 days after last install activity
* durable install identity, channel posture, and last-seen release truth: retain while the install relationship remains active
* superseded claim artifacts should collapse into one current install record plus bounded historical receipts

Redaction baseline:

* never persist personalized binary data because the binary remains canonical and signed
* keep person, install, device-role, and campaign scopes explicit instead of flattening them into a single sync blob

### Survey and follow-up results

Owner: `chummer6-hub`

Retention posture:

* post-fix follow-up invites and answer summaries: retain for 365 days
* raw free-text survey payloads: summarize or redact within 180 days unless still tied to an open product-governor packet

Redaction baseline:

* keep survey truth out of public guide copy until synthesized into canon
* redact install/account data that is not required for the follow-up question being answered

### Provider traces and assistant grounding packs

Owner: `executive-assistant` plus the owning product surface

Retention posture:

* raw provider request/response traces: retain for 30 days unless a narrower provider contract says less
* lane-level scorecards, challenger briefs, and grounding-pack summaries: retain for 180 days
* promoted help/support/public-answer truth must be rebuilt from canonical sources, not from indefinite provider transcripts

Redaction baseline:

* no unbounded PII spill into provider prompts, logs, or eval traces
* grounding packs should prefer case IDs, release IDs, and rule receipt IDs over raw user text where possible

### Publication and artifact telemetry

Owner: `chummer6-media-factory` plus `chummer6-hub-registry`

Retention posture:

* artifact manifests, provenance receipts, and compatibility records: retain while the artifact remains published plus 18 months
* stale previews and revoked artifacts: keep the receipt chain, but purge superseded raw render intermediates within 90 days

Redaction baseline:

* public trust surfaces should expose provenance and moderation state, not hidden operator notes or raw provider payloads

## Surface redaction rules

### Public surfaces

* may expose support status, known issues, release posture, compatibility, provenance, and channel-aware fix availability
* may not expose private case notes, raw crash envelopes, provider traces, or account-internal survey payloads

### Signed-in user surfaces

* may expose case timeline, install posture, claimed-device state, and the user-safe slice of crash/support data
* may not expose unrelated reporter data, operator-only packet deliberation, or private moderation notes

### Operator and governor surfaces

* may access bounded packet, cluster, and receipt truth needed for reroute, freeze, release, or close decisions
* must still prefer redacted or summarized payloads over indefinite raw-body retention

### Provider-backed assistant surfaces

* must ground answers in curated canonical sources, registry truth, or support-case truth
* must not become the system of record for support or release state

## Repo ownership split

* `chummer6-hub` owns user-visible support, case, survey, and install-link retention truth
* `chummer6-hub-registry` owns install/update/release/public-trust projections that depend on retained release records
* `fleet` owns bounded operator incident and publish-history evidence, not the whole-user truth
* `executive-assistant` owns route-steering traces and grounding-pack summaries, not public or support system-of-record semantics
* `chummer6-media-factory` owns render receipts, preview supersession, and revoked artifact handling

## Release and audit gates

* a surface that persists raw secrets, raw provider traces, or undefined retention windows fails release signoff
* a new assistant/help/provider integration must declare redaction and retention posture before it can be promoted
* product-governor review may freeze a wave when retention or privacy posture drifts behind shipped user trust claims
