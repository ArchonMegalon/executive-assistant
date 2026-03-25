# Roaming workspace and entitlement sync

## Purpose

This file defines how claimed installs unlock trustworthy cross-device continuity without turning Chummer into a mystery cloud blob.

The user-facing promise is:

> claim a device once, and Chummer restores your runners, campaigns, rule environment, and eligible features through the right authority instead of guessing with raw file sync

## Canonical principle

Sync typed product state through the right authority.

Do not treat roaming workspace as:

* a hidden backup dump
* a raw `.chumX` file mirror
* a synced `isPremium=true` flag
* a reason to mutate signed installers

## Roaming scopes

### Person scope

Belongs to one human across claimed installs.

Includes:

* profile and preferences
* pinned runners and recent campaigns
* personal draft rule-environment refs
* personal artifact-shelf refs
* notification posture

### Campaign or group scope

Belongs to a campaign, crew, GM circle, or creator team rather than one machine.

Includes:

* active crew and campaign membership
* campaign roster and campaign rule environment
* shared dossiers, recaps, and artifact refs
* group-owned rights and allowances

### Install scope

Stays local to one device.

Includes:

* caches
* logs and crash dumps
* rollback window
* hardware-specific tuning
* local secrets and key material
* explicit device role posture such as `workstation`, `play_tablet`, `observer_screen`, `travel_cache`, or `preview_scout`
* device-local channel posture such as "this machine is Preview, that one stays Stable"

### Entitlement scope

Never syncs as install-local booleans.

Entitlements resolve from Hub truth and may grant:

* premium features
* preview or private channel access
* GM or creator tools
* quotas or allowances
* group-owned rights

Clients may cache short-lived capability grants for offline grace periods, but Hub truth remains authoritative.

## Synced product state

### Living dossier, not raw character file

Roaming workspace restores a runner as a living dossier with:

* dossier identity
* build receipt and provenance refs
* campaign and crew bindings
* active gear and lifestyle posture
* immutable snapshots plus draft branches
* recap and continuity links

### Rule environment, not ad hoc house-rule blobs

A `RuleEnvironment` is a versioned environment reference that may carry:

* source pack refs
* house-rule pack refs
* option toggles
* compatibility fingerprint
* owner scope: `person`, `campaign`, or `group`
* approval state when governed promotion is required

### Artifact shelf, not naive blob mirroring

Generated outputs follow the user by manifest or reference:

* recent exports
* dossiers and recap packets
* portrait and media refs
* generated-from runner and rule-environment linkage
* availability state such as open locally, redownload, or open in browser

### Workspace restore cues

A claimed second device should be able to say:

* here are your recent runners
* this runner belongs to a specific campaign
* there is a newer draft on another device
* this campaign requires a different rule environment
* this install is eligible for a feature, but that eligibility came from Hub truth rather than a local toggle

## What never syncs

Do not sync:

* logs
* crash dumps
* updater rollback payloads
* install secrets or keypairs
* absolute file paths
* hardware-specific tuning
* silent plugin or script cargo
* raw premium-enabled booleans

## Authority split

### `chummer6-hub`

Owns:

* person, campaign, and group-scoped roaming workspace truth
* runner, dossier, crew, and campaign restore projections
* rule-environment refs and approval posture
* entitlement resolution and capability-grant issuance

### `chummer6-hub-registry`

Owns:

* immutable install, artifact, compatibility, and update truth
* claimed-install linkage and install compatibility posture
* artifact manifests and redownload-safe references

### `chummer6-ui`

Owns:

* desktop restore surfaces
* compare, branch, and repair affordances
* local per-install channel selection and apply behavior

### `chummer6-mobile`

Owns:

* local-first resume shell
* offline cache posture
* travel-safe continuity UX

### `chummer6-core`

Owns:

* deterministic receipts
* ruleset and pack provenance atoms
* compatibility inputs consumed by rule-environment refs

### `chummer6-media-factory`

Owns:

* rendered artifacts and previews

It does not own artifact-shelf truth, dossier identity, or campaign continuity semantics.

## Contract posture

`Chummer.Campaign.Contracts` should carry:

* runner and dossier restore refs
* crew and campaign continuity refs
* rule-environment refs and compatibility fingerprints
* workspace restore and conflict summaries

`Chummer.Hub.Registry.Contracts` should carry:

* claimed-install linkage
* install compatibility and channel posture
* artifact manifests and immutable publication refs

Hub-owned entitlements remain durable truth above install-local caches.

## Conflict rules

* No silent last-write-wins merge is allowed for dossiers, campaigns, or rule environments.
* Preferences may use field-level merge when the semantics are obvious.
* Entitlements are Hub-wins and client-read-only except for local cache expiry.
* Artifacts are immutable refs and therefore do not merge.
* A rule-environment mismatch must be explicit before a client computes against the wrong pack set.
* If a newer dossier draft exists elsewhere, the user must get an explicit latest, compare, branch, or stay-local choice.

## First-wave UX

### Claim restore sheet

After claim, the user may opt into restoring:

* runners and dossiers
* recent campaigns
* rule environments
* artifacts and exports
* eligible premium features
* notification channels

### Second claimed device

A newly claimed device should feel like:

* welcome back
* here are your recent runners and campaigns
* this campaign needs a specific rule environment
* these features are available through your account or group
* this install is currently pinned to its own channel posture

### Continue where I left off

The home surface should be able to project:

* last runner
* last campaign
* unresolved restore conflict
* missing rule pack on this device
* feature unlocked through entitlement truth

## Campaign workspace and device-role handoff

Roaming workspace makes cross-device continuity possible, but the lived product surface is the campaign workspace and the install's device role.

That next layer is defined in:

* `CAMPAIGN_WORKSPACE_AND_DEVICE_ROLES.md`

Roaming workspace therefore must preserve enough truth for the home cockpit or campaign workspace to answer:

* what changed for me
* which campaign needs attention
* whether this device is acting as a workstation, play tablet, observer screen, travel cache, or preview scout
* what the next safe action is

## Horizon handoff

The base capability is current canon, not a far-future horizon.

Future-most layers project into existing horizons:

* `horizons/nexus-pan.md` for richer cross-device handoff, travel prefetch, and continuity follow-me behavior
* `horizons/karma-forge.md` for governed house-rule promotion and reusable rule-environment sharing
* `horizons/jackpoint.md` for a deeper artifact shelf and richer publication follow-through

## Non-goals

This file does not:

* create personalized installers
* redefine raw engine pack ownership
* make Hub the source of immutable artifact bytes
* promise silent background merge magic
