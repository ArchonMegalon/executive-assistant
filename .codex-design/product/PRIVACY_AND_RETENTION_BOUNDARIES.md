# Privacy and retention boundaries

## Purpose

This file defines the default privacy, retention, and redaction rules for Chummer account, support, and feedback data.

It exists so support notes, crash reports, install links, surveys, help conversations, and outside-service logs do not silently turn into an unlimited archive.

The product-steering telemetry model and concrete opt-out event schema that sit inside these boundaries are defined in `PRODUCT_USAGE_TELEMETRY_MODEL.md` and `PRODUCT_USAGE_TELEMETRY_EVENT_SCHEMA.md`.
User-contribution privacy, IP, and visibility rules for BLACK LEDGER intel, house-rule submissions, open-run applications, session debriefs, media files, public feedback, and creator submissions are defined in `USER_CONTRIBUTION_PRIVACY_AND_IP_POLICY.md` and `USER_CONTRIBUTION_VISIBILITY_REGISTRY.yaml`.

## Default rules

* retain the smallest amount of data that still allows honest closure, replay-safe support, and useful follow-up
* keep install-local secrets, raw auth tokens, updater rollback payloads, and local caches on the install unless canon explicitly promotes them
* prefer structured summaries and short-lived records over indefinite raw payload retention
* outside-service logs must be redacted before persistence unless the owning surface explicitly declares otherwise
* every retained surface needs an owner, a retention clock, a redaction posture, and a delete-or-summarize rule

## Retention domains

### Support-case truth

Owner: `chummer6-hub`

Retention posture:

* case timeline and user-visible status events: retain for 18 months after the last state change
* public known-issue linkage and closure records: retain for 18 months after public closure
* raw attachments that are no longer needed for open investigation: summarize or redact within 90 days

Redaction baseline:

* remove secrets, local paths, and unrelated identity data from user-visible case history
* preserve bounded install/channel/version truth needed for honest fix-availability notices

### Crash envelopes

Owner: `chummer6-hub`

Retention posture:

* raw crash reports: retain for 90 days unless tied to an active blocker or open case cluster
* crash summaries and grouped issue records: retain for 18 months
* local crash dumps remain install-local unless explicit user action uploads them

Redaction baseline:

* no passwords, tokens, or local machine credentials in retained crash payloads
* strip or hash install-local absolute paths when they are not required for a live investigation

### Claim and install linkage

Owner: `chummer6-hub` plus `chummer6-hub-registry`

Retention posture:

* claim tickets and install-link events: retain for 365 days after last install activity
* durable install identity, channel posture, and last-seen release status: retain while the install relationship remains active
* older claim files should collapse into one current install record plus limited historical records

Redaction baseline:

* never persist personalized binary data because the binary remains canonical and signed
* keep person, install, device-role, and campaign scopes explicit instead of flattening them into a single sync blob

### Product usage telemetry

Owner: `chummer6-hub` plus `fleet`

Retention posture:

* raw hosted product-improvement event envelopes: retain for 30 days or less, then collapse into bounded daily rollups
* install-linked daily usage rollups: retain for 18 months
* explicit debug-uplift telemetry tied to a support case or beta investigation: retain only while the case or investigation is active, then delete or summarize within 30 days

Redaction baseline:

* retain package IDs, fingerprints, buckets, and counters instead of raw character content, campaign content, or houserule bodies
* no character names, campaign names, notes, free text, or full custom-data blobs in the default hosted telemetry plane
* install-linked telemetry is opt-out by default, pseudonymous by default, and must not be repurposed as a marketing profile

### Survey and follow-up results

Owner: `chummer6-hub`

Retention posture:

* post-fix follow-up invites and answer summaries: retain for 365 days
* raw free-text survey answers: summarize or redact within 180 days unless still tied to an open product decision

Redaction baseline:

* keep survey truth out of public guide copy until synthesized into canon
* redact install/account data that is not required for the follow-up question being answered

### Help-service logs and answer notes

Owner: `executive-assistant` plus the owning product surface

Retention posture:

* raw outside-service request and response logs: retain for 30 days unless a narrower service contract says less
* service comparison notes and answer summaries: retain for 180 days
* promoted help, support, and public answers must be rebuilt from Chummer sources, not from indefinite outside-service transcripts

Redaction baseline:

* no unbounded personal data spill into prompts, logs, or review traces
* answer notes should prefer case numbers, release numbers, and calculation records over raw user text where possible

### User contribution and external workbench projections

Owner: `chummer6-hub`

Retention posture:

* Teable/AdminIntent projection rows: retain only while the source queue item is active, then collapse into a follow-up record and source-object history
* raw user submissions in external intake tools: copy needed records into Hub, then summarize or delete from the external tool according to the contribution class
* public-safe contribution summaries and credit records: retain while the contribution is published plus 18 months

Redaction baseline:

* never collect raw sourcebook text, private table spoilers, faction secrets, or support notes into public or vendor-visible contribution queues unless a Hub-owned projection explicitly permits the field
* private submissions must move through visibility classes before becoming public lore, job seeds, map markers, videos, newsletters, or Signitic/Emailit campaign payloads

### Publication and file records

Owner: `chummer6-media-factory` plus `chummer6-hub-registry`

Retention posture:

* file manifests, origin records, and compatibility records: retain while the file remains published plus 18 months
* stale previews and revoked files: keep the history, but purge superseded raw render intermediates within 90 days

Redaction baseline:

* public trust surfaces should expose origin and moderation state, not hidden maintainer notes or raw outside-service payloads

## Surface redaction rules

### Public surfaces

* may expose support status, known issues, release posture, compatibility, origin, and channel-aware fix availability
* may not expose private case notes, raw crash reports, outside-service logs, or private survey text

### Signed-in user surfaces

* may expose case timeline, install posture, claimed-device state, and the user-safe slice of crash/support data
* may not expose unrelated reporter data, maintainer-only notes, or private moderation notes

### Operator and governor surfaces

* may access limited case, cluster, and record details needed for reroute, freeze, release, or close decisions
* must still prefer redacted or summarized payloads over indefinite raw-body retention

### Help tool surfaces

* must ground answers in curated canonical sources, registry truth, or support-case truth
* must not become the system of record for support or release state

## Repo ownership split

* `chummer6-hub` owns user-visible support, case, survey, and install-link retention truth
* `chummer6-hub-registry` owns install/update/release/public-trust projections that depend on retained release records
* `fleet` owns limited maintainer incident and publish-history evidence, not the whole-user record
* `executive-assistant` owns route-steering logs and answer summaries, not public or support system-of-record semantics
* `chummer6-media-factory` owns render records, preview supersession, and revoked file handling

## Release and audit gates

* a surface that persists passwords, raw outside-service logs, or undefined retention windows fails release signoff
* a new help or outside-service integration must declare redaction and retention posture before it can be promoted
* product review may freeze a wave when retention or privacy posture drifts behind shipped user trust claims
* any new contribution, Teable, Emailit, Signitic, ProductLift, Icanpreneur, Hedy, Nonverbia, Unmixr, or Deftform workflow must declare contribution class, visibility class, redaction posture, and delete-or-summarize rule before promotion
