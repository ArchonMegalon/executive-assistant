# Product usage telemetry model

## Purpose

This file defines the telemetry Chummer should gather to steer future product work without turning personalized installs into a surveillance system.

The point is not "collect everything."
The point is to answer a small number of high-value product questions honestly:

* which languages are actually used
* which rulesets are actively used versus merely present
* which amend packages and houserule bundles matter enough to support first-class
* how many real program starts happen per day and on which platform/channel/head
* where users drop out, fail, or repeatedly need recovery
* which install topologies and sync postures are actually used versus merely configured
* where performance and reliability fall apart only on larger or more customized installs
* which accessibility and input postures must stay release-gated instead of "best effort"
* where search, discovery, and empty-state posture make users think Chummer cannot do something it actually can
* which release, migration, and workflow investments would pay back the most user pain

Privacy, retention, and redaction boundaries still live in `PRIVACY_AND_RETENTION_BOUNDARIES.md`.
Concrete event names, rollup shapes, and install-level settings live in `PRODUCT_USAGE_TELEMETRY_EVENT_SCHEMA.md`.

## Non-goals

This file does not allow:

* a raw character-sheet warehouse
* indefinite storage of granular behavior traces
* free-text upload by default for roadmap analytics
* collection of full houserule bodies when package IDs or fingerprints are enough
* collection of campaign names, runner names, contact lists, or notes for product steering
* turning install-linked telemetry into ad-targeting or dark-pattern experimentation

## Core rule

Telemetry must be useful enough to change roadmap and release decisions.
If a field cannot plausibly change prioritization, quality policy, localization policy, or support posture, it probably should not be retained.

## Default posture

Chummer should treat product-improvement telemetry as opt-out, not opt-in.

That means:

* Tier-2 product telemetry is on by default for normal releases
* the first-run explanation is plain language, not a trap door or dark pattern
* the user can turn it off immediately during first run and later in settings
* turning it off stops new hosted Tier-2 telemetry emission and clears any unsent hosted analytics spool
* install-local history may remain on-device even when hosted telemetry is off
* Tier-3 debug uplift for support, beta, or incident diagnosis remains explicit opt-in outside crash recovery
* after a crash, the crash handler may temporarily arm crash-focused debug uplift for the next launch and recovery flow
* that crash-triggered debug uplift must immediately offer an opt-out and remember the decision on the install
* Hub may retain one minimal telemetry-preference receipt for a claimed install so the opt-out itself is honored across reinstall, recovery, or linked-device continuity

## Telemetry tiers

### Tier 1: install-local history

Lives on the device unless the user explicitly shares it through support or diagnostics.

Use it for:

* recent sessions
* local crash and startup recovery context
* "what changed on this machine" explanations
* support bundles the user can review before upload

Tier-1 data may be richer than hosted telemetry because it stays local by default.

### Tier 2: pseudonymous hosted product telemetry

This is the default product-improvement telemetry layer for normal releases.
It is opt-out: on by default, clearly disclosed, and user-disableable at any time.
It should be install-linked and pseudonymous, not person-profiled.

Use it for:

* daily active installs
* program starts per day
* ruleset adoption
* locale adoption
* amend-package and houserule adoption via IDs or fingerprints
* workflow completion and abandonment
* update adoption
* startup and crash reliability

Tier-2 should prefer daily rollups and bounded counters over indefinitely retained raw event streams.

### Tier 3: explicit debug uplift

This is the temporary "help us diagnose this problem" layer tied to a support case, beta cohort, or time-boxed investigation.

Use it for:

* startup trace detail
* sync/recovery conflict detail
* import/export failure detail
* slow-path profiling snapshots
* richer package conflict diagnostics

Tier-3 must be explicit, time-bounded, and easy to turn off.
The narrow exception is crash recovery: the crash handler may auto-arm a temporary Tier-3 window for the immediate post-crash reopen, but it must surface an opt-out right there and remember if the user declines future crash-triggered debug uplift.

## Canonical dimensions

Every retained telemetry fact should be sliceable by the smallest set of dimensions that actually help product decisions.

### Install and release dimensions

* pseudonymous `installation_id`
* claimed versus guest install
* product head: desktop, browser, mobile, play shell
* platform and arch
* release channel
* app version
* first-install month cohort
* update source and upgrade-from version where relevant

### Language dimensions

* UI language
* content/data language where Chummer distinguishes it from UI language
* fallback-language usage

These should answer:

* which locales deserve flagship parity
* which locales are falling back too often
* which translations are present but barely used

### Rule-environment dimensions

* active ruleset
* preset ID
* enabled source-pack set
* amend-package IDs
* custom-data present: yes or no
* custom package count bucket
* houserule fingerprint set

The hosted layer should never require raw houserule text.
Use package IDs when the rules are known and stable fingerprints when they are install-local.

### Install-topology dimensions

* standalone versus Hub-linked posture
* managed Hub versus self-hosted Hub topology
* sync enabled: yes or no
* online versus offline recovery posture where relevant

These should answer:

* whether the next investment belongs in pure desktop, Hub continuity, or offline resilience
* whether self-hosted installs are common enough to support as first-class, not just tolerated

### Complexity dimensions

* saved-character count bucket
* roster size bucket
* source-pack count bucket
* custom package count bucket
* workspace scale bucket

These should answer:

* whether startup, save, or import pain is general or concentrated in larger installs
* whether a complaint is really about complexity posture instead of a universal defect

### Accessibility and input dimensions

* input posture: keyboard-primary, pointer-primary, touch-primary, mixed
* font-scale bucket
* high-contrast enabled
* reduced-motion enabled
* screen-reader enabled

These should answer:

* which accessibility modes are common enough to gate release quality
* whether flagship polish is only good on the default visual/input posture

### Workflow dimensions

* entry path: open existing character, create new, import legacy file, open roster, open master index, open campaign workspace, continue recovery, launch play shell
* major workflow family: build, explain, run, publish, improve
* completion state: started, completed, abandoned, failed, recovered

## What Chummer should actually gather

### 1. Daily install activity

Minimum useful facts:

* unique active installs per day and week
* program starts per day
* cold starts versus warm resumes
* median startup time by platform, channel, and head
* crash-before-ready rate
* recovery-dialog frequency

This is the simplest honest "is the product alive and healthy" signal.

### 2. Language adoption

Gather:

* daily active installs by UI language
* starts by UI language
* completion of first-run and core workflows by UI language
* fallback-string exposure rate by language

This tells Chummer whether localization work should target breadth, depth, or parity repair.

### 3. Ruleset adoption

Gather:

* daily active installs by ruleset
* starts by ruleset
* new-character flow starts by ruleset
* save/build/print/export usage by ruleset
* ruleset-specific error rates

This separates "installed because it exists" from "actually used in live play and build sessions."

### 4. Houserule and amend-package adoption

Gather:

* amend-package usage by package ID
* custom-data present rate
* top houserule fingerprint bundles
* build/save/import failure rate when custom data or houserules are active
* top conflicting package combinations

This is how Chummer learns which homebrew patterns should graduate into first-class support instead of staying community folklore.

### 5. Install topology and sync posture

Gather:

* standalone versus claimed-install usage
* managed-Hub versus self-hosted-Hub usage
* sync-enabled rate and multi-device continuity rate
* offline-start and offline-recovery rate for linked installs
* sync-conflict and restore-conflict rate by topology

This tells Chummer whether future platform work should favor pure local flow quality, Hub continuity, self-hosted support, or offline resilience.

### 6. Complexity and scale telemetry

Gather:

* saved-character count bucket
* roster size bucket
* source-pack count bucket
* custom package count bucket
* workspace scale bucket
* startup/save/import failure rate by scale bucket

Never upload raw inventory when a bucket is enough.
This is how Chummer separates "the app is slow" from "the app is slow on very large personalized installs."

### 7. Workflow funnels

Gather bounded funnel facts for high-value journeys:

* install -> first launch -> claim/skip -> first successful open or build
* open existing character -> edit -> save
* import legacy file -> repair prompts -> successful open
* update available -> update start -> relaunch success
* crash -> recovery -> successful reopen

For each funnel, gather:

* started count
* completed count
* abandon count
* failure count
* median time-to-complete

### 8. Feature adoption

Gather:

* master index opens
* character roster usage
* build-lab usage
* print/export format usage
* campaign workspace usage
* play shell usage
* explain or breakdown usage
* compare or diff usage

This helps distinguish "loud requested feature" from "quietly central daily tool."

### 9. Search and findability telemetry

Gather:

* master-index search count
* help/search surface usage count
* zero-result rate by surface, ruleset, and locale
* result-open rate after search
* empty-state exposure count for major surfaces

Do not keep raw query text.
Count result buckets, selection rate, and zero-result posture instead.

This is how Chummer learns whether the problem is missing capability, missing terminology, or bad discoverability.

### 10. Friction telemetry

Gather:

* import failure classes
* save failure classes
* sync or restore conflict classes
* updater failure classes
* startup failure classes
* slow operation buckets
* repeated validation-error classes

Do not just count crashes.
Count the non-crash pain that causes repeated rework.

### 11. Release and migration telemetry

Gather:

* upgrade adoption by release channel
* downgrade or rollback frequency
* upgrade-from version distribution
* legacy import usage by source family
* time-to-adopt for promoted releases

This tells release control whether the real bottleneck is packaging, trust, compatibility, or migration friction.

### 12. Telemetry trust and control

Gather:

* Tier-2 opt-out rate by platform, head, and release channel
* first-run telemetry choice timing bucket
* crash-triggered debug uplift decline rate
* support-driven debug uplift accept rate

Do not collect free-text reasons here.
If a reason is gathered, it should be one bounded enum, not a text box.

### 13. Accessibility and input posture

Gather:

* high-contrast usage rate
* reduced-motion usage rate
* screen-reader enabled rate
* font-scale bucket adoption
* keyboard-first versus pointer-heavy posture
* completion and failure rate by accessibility posture

Only capture bounded posture flags and buckets, not OS-specific assistive metadata.
This keeps flagship quality anchored to the modes real users rely on, not just the default happy path.

## High-value derived metrics

The product-governor dashboard should be able to answer these without ad hoc research:

* daily and weekly active installs
* starts per active install
* startup success rate
* first-launch success rate
* ruleset share of active use
* language share of active use
* percent of active installs using custom data or houserules
* active installs by connectivity posture
* top amend-package IDs by active use
* top houserule fingerprints by active use
* zero-result search rate by surface
* import success rate
* update-to-relaunch success rate
* startup and save reliability by install complexity bucket
* save reliability by ruleset and custom-data posture
* crash-free starts by platform and channel
* active installs using high-contrast, large-font, or screen-reader posture
* Tier-2 opt-out rate
* crash-triggered debug-uplift decline rate

## Smart product questions this should answer

### Language

Should German, French, Spanish, or another locale get the next flagship localization wave?
Answer from active installs, starts, and workflow success by locale, not from download totals alone.

### Ruleset

Should SR5, SR6, or another ruleset get the next polish or parity wave?
Answer from active usage and failure-adjusted workflow volume, not from forum noise alone.

### Houserules

Which houserules should become first-class modeled options?
Answer from stable package IDs or repeated fingerprint clusters, plus the pain they currently cause.

### Startup and desktop quality

Did the new release actually improve the real app-open experience?
Answer from starts per day, crash-before-ready, recovery frequency, and startup latency by platform.

### Topology and sync

Should the next platform cycle favor standalone desktop quality, Hub continuity, or self-hosted support?
Answer from active installs, conflict rate, and offline recovery behavior by topology.

### Complexity and scale

Are the worst complaints really general, or concentrated in larger rosters and heavy custom-data installs?
Answer from startup, save, and import reliability by scale bucket.

### Workflow investment

Should the next cycle favor import, roster, campaign workspace, explain, or build-lab work?
Answer from actual workflow starts, completions, abandons, and repeated pain signals.

### Accessibility

Which accessibility postures are common enough to be release gates, not afterthoughts?
Answer from active installs and workflow success by high-contrast, reduced-motion, screen-reader, and large-font posture.

## Canonical data shapes

The hosted layer should prefer a few durable rollups:

### `install_activity_daily`

One row per install per day with:

* start count
* ready count
* crash-before-ready count
* total foreground minutes bucket
* head, platform, channel, version, locale, ruleset mix summary

### `rule_environment_daily`

One row per install/ruleset/day with:

* ruleset
* preset ID
* source-pack set hash
* amend-package IDs
* houserule fingerprint set
* custom-data present flag
* build/save/import/export counts

### `install_context_daily`

One row per install/day with:

* connectivity posture
* hub topology
* sync enabled flag
* saved-character count bucket
* roster size bucket
* source-pack count bucket
* workspace scale bucket

### `workflow_funnel_daily`

One row per journey/day with:

* journey ID
* started
* completed
* abandoned
* failed
* median duration bucket

### `search_usage_daily`

One row per install/day/surface with:

* surface ID
* query count
* zero-result count
* result-open count
* empty-state count

### `friction_rollup_daily`

One row per install/day/problem class with:

* problem family
* error class
* affected workflow
* count

### `telemetry_preference_daily`

One row per install/day whenever preference changes with:

* telemetry state
* change source
* reason code
* crash-debug enabled flag

### `accessibility_posture_daily`

One row per install/day with:

* dominant input posture
* dominant font-scale bucket
* any high-contrast enabled
* any reduced-motion enabled
* any screen-reader enabled

## Privacy rules specific to this telemetry

The default hosted telemetry layer must not retain:

* character names
* runner names
* campaign names
* free-text notes
* chat or table transcripts
* raw houserule text
* full custom-data blobs
* full file paths
* exported character content

When a product question can be answered by a counter, bucket, package ID, or fingerprint, that smaller fact is the canonical choice.

## Ownership split

### `chummer6-design`

Owns:

* which telemetry questions are legitimate
* the canonical event and rollup vocabulary
* privacy boundaries for product-steering telemetry
* the rule that install-linked telemetry stays pseudonymous by default

### `chummer6-hub`

Owns:

* telemetry intake
* opt-in controls
* install-linked aggregation
* retention enforcement for hosted telemetry

### `fleet`

Owns:

* aggregated product-steering dashboards
* anomaly detection
* release and friction clustering
* routing signals into roadmap and support loops

Fleet should consume bounded rollups, not become the long-term raw telemetry warehouse.

### `chummer6-ui`

Owns:

* local event emission
* install-local history
* clear user-facing opt-out and debug-uplift controls
* support-bundle uplift when the user explicitly shares richer diagnostics

## Implementation order

1. daily install activity, starts, ready-state, and crash-before-ready
2. language and ruleset rollups
3. install topology and scale rollups
4. amend-package and houserule fingerprint rollups
5. core workflow funnels
6. search and friction rollups
7. telemetry preference receipts
8. explicit debug uplift for support and beta investigations
9. accessibility posture rollups

## Rule

If a future dashboard cannot answer "who is using which language, which ruleset, which houserule posture, on which platform, and where they fail" without pulling raw personal content, the telemetry model was designed badly.
