# Desktop auto-update system

## Purpose

This file defines how installable desktop clients become self-updating without collapsing current ownership boundaries.

The target experience is:

* a user installs Chummer from a Windows `.exe`, macOS `.dmg`, or Linux `.deb`
* the desktop client can later check for updates in-app
* the client can later either stage an in-place payload or hand off a newer platform installer
* release channels, promoted heads, rollout state, and revocation truth remain registry-owned
* the updater stays atomic in its first wave so app and runtime skew does not become a hidden source of corruption
* the public downloads shelf stays installer-only rather than falling back to portable archives

## Non-goals

This file does not define:

* mobile or PWA update policy
* store-managed update channels such as MSIX, App Installer, or App Store distribution
* a requirement to use one updater backend forever
* runtime-bundle-only updates in the first wave
* Fleet or Hub as the runtime source of update truth for the client

## Canonical terms

### Desktop head

A ship-ready desktop client flavor keyed by at least:

* `head_id`
* `platform`
* `arch`
* `channel`
* `version`

This model is intentionally head-agnostic. It does not force canon to pick one desktop shell technology before the release head shape is defined.

### Install media

A human-facing first-install artifact such as:

* Windows installer `.exe`
* macOS installer `.dmg`
* Linux installer `.deb`

### Machine update payload

A client-facing staged-update artifact used for in-place application updates or installer handoff. This may be a full package in phase 1 and may later gain delta variants.

### Desktop release head

The registry-owned promoted record for one `head × platform × arch × channel` target. It points at the current install media, current machine update payload, embedded runtime-bundle head, release notes, rollout posture, and revoke state.

### Apply helper

A UI-owned process that performs file replacement, rollback-window bookkeeping, and relaunch after the user approves or policy allows an update.

### Rollout posture

Registry-owned promotion state for a desktop release head. Minimum first-wave states are:

* `open`
* `paused`
* `revoked`

## Canonical split

### `chummer6-design`

Owns:

* updater architecture canon
* ownership rules
* milestone truth
* contract-family registration
* rollout and non-goal boundaries

Must not own:

* updater code
* packaging scripts
* feed-serving runtime code

### `chummer6-ui`

Owns:

* updater client behavior inside desktop heads
* local install identity and pinned-channel state
* check, download, stage, apply, and relaunch UX
* apply helper binaries and platform-specific file-replacement logic
* update settings and about surfaces
* rollback-window bookkeeping

Must not own:

* canonical channel or update-feed truth
* rollout, pause, or revoke state for promoted heads
* public release-head promotion
* runtime-bundle canon

### `chummer6-hub-registry`

Owns:

* promoted desktop release heads
* install media records
* machine update payload records
* update-feed vocabulary and DTOs
* rollout, pause, and revoke truth
* compatibility projections for shipped heads
* embedded runtime-bundle references

Must not own:

* client-side apply logic
* installer build execution
* signing or notarization jobs
* public landing copy authority

### `fleet`

Owns:

* build, sign, notarize, and promote orchestration
* release evidence, readiness gates, and publication payload assembly
* emergency promotion or revoke workflow execution

Must not own:

* updater client behavior
* runtime update-feed authority
* canonical desktop channel truth

### `chummer6-hub`

Owns:

* public download and install guidance UX
* account-aware install suggestions
* optional entitlement brokering for gated desktop channels

Must not own:

* public update-feed truth
* local update polling or apply logic
* canonical promoted desktop head state

## Phase 1 shape

Phase 1 desktop auto-update is intentionally conservative:

* public channels are registry-backed and pollable without a Hub account session
* the app shell and embedded runtime bundle update atomically as one promoted desktop head
* install media and machine update payloads are distinct artifact classes even when a lane publishes installers only
* the updater may be automatic or user-approved, but apply authority stays in the UI-owned client helper
* every desktop release wave builds Windows, macOS, and Linux install media even when public promotion remains per-platform

## Client behavior

The desktop client must:

* record installed version, platform, arch, and pinned channel locally
* fetch release-head or feed truth from `chummer6-hub-registry`
* validate signature and digest material before apply
* stage updates before replacing the live installation or launching the next installer handoff
* keep a last-known-good rollback window until first successful launch of the new head
* honor paused or revoked heads

The client must not:

* invent local promoted-channel semantics
* treat Fleet endpoints or Hub pages as canonical feed truth
* auto-accept downgrades unless registry policy explicitly allows them

## Registry behavior

The registry must publish a desktop release head keyed by `head × platform × arch × channel` that includes:

* install media references
* machine update payload references
* version and release-note references
* embedded runtime-bundle head reference
* rollout posture
* revoke state
* compatibility metadata needed for safe client decisions

## Release orchestration behavior

Fleet owns the release lane that:

* builds desktop heads
* emits Windows `.exe`, macOS `.dmg`, and Linux `.deb` installer targets
* runs platform-appropriate startup smoke checks that actually launch each built head
* signs and notarizes them where required
* verifies digests and evidence
* publishes installer-only bundles into the generated downloads shelf used for local and self-hosted verification
* routes startup smoke crashes into the release-regression OODA loop before promotion
* promotes or revokes registry-backed desktop heads

Fleet may orchestrate the workflow, but it must not become the runtime system of record for clients.

## Recovery rules

If a promoted head is revoked:

* clients must not auto-apply it
* guidance surfaces may direct users to reinstall or roll back
* registry truth stays authoritative about which head is safe

If an apply attempt fails:

* the UI-owned helper is responsible for rollback or recovery guidance
* Hub may render user-facing recovery help
* Fleet may provide evidence and promotion controls, but not local apply logic
