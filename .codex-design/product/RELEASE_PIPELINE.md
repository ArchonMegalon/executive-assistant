# Release pipeline canon

## Purpose

This file defines where Chummer release authority lives after the split.

The goal is to keep build recipes near the owning code, keep release control in one place, and keep public install/update truth in one registry-owned plane.

## Canonical split

### `chummer6-core`

Owns:

* runtime-bundle production
* runtime-bundle fingerprints
* ruleset/profile/build-axis truth that changes the runtime bundle matrix
* engine-side compatibility facts needed to explain or validate a runtime bundle

Must not own:

* installer packaging
* release-channel promotion
* public download UX
* updater feed publication policy

### `chummer6-ui`

Owns:

* desktop packaging recipes
* installer production recipes
* updater integration inside the desktop heads
* Windows installer `.exe`, macOS installer `.dmg`, and Linux installer `.deb` target production
* local install/channel state for desktop clients
* staged apply helpers and relaunch flow for desktop updates
* workbench-side release polish
* release-bundle emission for desktop artifacts
* the post-build sync step that replaces the public downloads shelf with the latest successful bundle when a deploy target is configured

Must not own:

* release orchestration across repos
* canonical channel truth
* canonical update-feed truth
* runtime-bundle authority
* public download/install ledger truth

### `fleet`

Owns:

* release matrix expansion
* release orchestration across owning repos
* verify gates, promotion gates, and readiness evidence
* publish history and compile-manifest evidence for the release lane
* signing/notarization job orchestration when those jobs are part of the release wave
* downstream public-guide and status projections that compile from design and registry truth

Must not own:

* installer recipe truth
* updater client behavior
* runtime-bundle canon
* canonical release-channel state
* canonical installer/update-feed metadata

### `chummer6-hub-registry`

Owns:

* release channels and promoted channel heads
* install/update metadata
* installer/download artifact records once promoted
* desktop release heads by `head × platform × arch × channel`
* updater feed metadata
* rollout, pause, and revoke truth for promoted desktop heads
* compatibility truth for shipped heads and embedded runtime bundles
* runtime-bundle head metadata

Must not own:

* installer builds
* signing/notarization execution
* Hub landing-page copy authority
* media rendering
* updater apply logic inside the client

### `chummer6-hub`

Owns:

* public downloads UX
* account-aware install and entitlement UX
* signed-in "what should I install?" projections
* public rendering of registry-owned release/install/update truth

Must not own:

* release manifest generation authority
* installer/update-feed truth
* long-term release-channel truth
* client-side update decisioning or apply logic

### `chummer6-media-factory`

Owns only render-side release adjuncts:

* screenshots
* preview images
* share cards
* bounded release-note visuals

It must not own installers, release feeds, channel policy, or publication/update truth.

## Artifact classes

Chummer keeps human install media and machine update payloads distinct.

### Human install media

These are user-facing first-install artifacts:

* Windows installer `.exe`
* macOS installer `.dmg`
* Linux installer `.deb`

### Machine update payloads

These are updater-facing artifacts consumed by desktop clients:

* full-head in-place update packages when a head emits them
* platform installer handoff packages when the published lane is installer-only
* optional later delta packages
* release-note references and staged-apply metadata

The registry is the canonical source for both classes after promotion. The UI repo is the owner of how clients consume machine update payloads.

## Claimable install rule

Chummer makes installs claimable and account-aware without personalizing the delivered binary.

Required posture:

* Hub-first downloads are preferred for end users
* public stable/open installers remain guest-readable
* signed-in downloads may mint Hub-owned `DownloadReceipt` and `InstallClaimTicket` records
* the downloaded artifact remains the canonical signed installer or update package for its `head × platform × arch × channel`
* linking happens after download or first launch, not by mutating the artifact

Forbidden posture:

* one installer per user
* post-sign mutation of a signed installer to inject account identity
* making Hub the canonical release/feed authority because install linking exists

## Canonical flow

1. `chummer6-core` produces runtime-bundle outputs and fingerprints.
2. `chummer6-ui` produces installer-ready desktop bundles for Windows `.exe`, macOS `.dmg`, and Linux `.deb`, plus any machine update payloads needed by the updater lane.
3. When a self-hosted downloads target is configured, the successful desktop build automatically replaces the previous public downloads bundle and prunes superseded desktop artifacts so `/downloads` stays latest-only.
4. `fleet` expands the release matrix, runs verify/promotion/signoff/signing/notarization orchestration, and prepares a registry publication payload.
5. `chummer6-hub-registry` becomes the source of truth for promoted channels, installer/download records, desktop release heads, update-feed metadata, compatibility, and runtime-bundle heads.
6. `chummer6-hub` reads registry truth, serves `/downloads`, mints optional download receipts and install-claim tickets, and renders account-aware install UX without changing the underlying artifact.
7. Desktop clients poll registry-backed channel/feed truth and apply updates through UI-owned helpers.
8. `Chummer6` and other downstream guide surfaces read registry-backed release projections; they do not become build authorities.

## Canonical release-manifest rule

Every promoted desktop release head must have one canonical release manifest.

Minimum manifest scope:

* product and channel identity
* per-repo commit set for the promoted build
* artifact digests and signature or notarization references
* embedded runtime-bundle fingerprint
* contract or package version floor where relevant
* registry publication receipt

Authority rule:

* Fleet prepares and verifies the candidate manifest during promotion.
* `chummer6-hub-registry` publishes the promoted manifest as canonical release truth.
* GitHub releases, `/downloads`, updater feeds, and downstream guide/status surfaces are projections from that registry-owned manifest.

Failure rule:

* promotion must fail if GitHub release notes, public downloads, updater metadata, or guide projections disagree with the canonical registry manifest for the same promoted head
* GitHub releases and public file shelves must never be treated as the authority that overrides registry channel truth

## Initial ship rule

Do not explode the first release wave into every theoretical combination.

Initial normal shape:

* one install medium per `head × platform × arch × channel`
* one machine update payload per promoted desktop release head
* selected runtime bundle embedded in that desktop head
* registry records which runtime-bundle head was embedded

Only split app-binary updates from runtime-bundle updates after the atomic desktop path is stable enough to avoid app/runtime skew.

## Atomic updater rule

Phase 1 desktop auto-update is atomic:

* the app shell and embedded runtime bundle advance together
* the updater stages a full replacement of the desktop head
* public channel truth points at one promoted head, not a bag of partially compatible pieces

Differential updates are allowed later, but only if the registry compatibility plane and milestone truth explicitly permit them.

## Cross-platform desktop build rule

Before a desktop release wave is considered promotion-ready, the release lane must build Windows `.exe`, macOS `.dmg`, and Linux `.deb` artifacts from the same release candidate.

This build rule exists to:

* keep Windows, macOS, and Linux as real release targets instead of letting one platform silently rot behind the others
* prove the desktop release matrix still materializes from one coherent release candidate
* keep internal and public release posture honest about which platform heads are actually buildable

A platform may remain unpublished or unpromoted on the public shelf, but lack of promotion does not exempt it from the build gate.

## macOS public shelf rule

macOS build success alone does not make macOS a public preview platform.

Before `/downloads`, release manifests, or public trust surfaces may present a macOS installer as available, the release lane must have:

* a signed `.dmg`
* notarization evidence for that `.dmg`
* release-truth promotion that marks the macOS lane public, not merely buildable

Until then:

* macOS artifacts may exist in internal bundles and release evidence
* startup smoke for macOS remains required
* public manifests and public file shelves must exclude the withheld macOS artifacts so users do not infer false availability from raw files

## Startup smoke rule

Every built desktop artifact must pass a platform-appropriate startup smoke test before the affected head is eligible for promotion.

Minimum smoke shape:

* install, mount, or unpack the artifact on a verification host for that platform
* launch the desktop head far enough to prove process start, first-window or ready-state bootstrap, and clean early initialization
* capture a bounded startup receipt with version, channel, platform, arch, artifact digest, and verification-host class

If a smoke start crashes or fails to reach the ready checkpoint:

* Fleet must emit a bounded release-regression packet with platform, arch, channel, head, version, artifact digest, crash fingerprint, and short log tail
* the product governor must OODA that packet as a release-regression signal and choose freeze, reroute, fix, or defer posture
* the failing platform head is not promotable again until a fresh build passes startup smoke

## Public auth rule

Public desktop update checks must not require a Hub account session for public channels. Private or entitlement-gated channels may use Hub-brokered access, but the final channel and update-feed truth still lives in `chummer6-hub-registry`.

## Gated-channel install rule

Public stable/open channels may remain anonymously downloadable and anonymously update-readable.

Preview, private, or entitlement-gated channels may require:

* a claimed installation
* Hub-brokered installation grants
* Registry-backed channel truth

That still does not justify personalized binaries.

## Emergency rule

A promoted desktop head may be:

* open
* paused
* revoked

The registry owns those states. The client honors them. Fleet may orchestrate the promotion or revoke wave, but it does not become the runtime source of truth for clients.

## Crash automation release rule

Crash-driven automation does not bypass the release plane.

Allowed shape:

* `chummer6-ui` sends redacted crash envelopes to Hub-owned intake
* `chummer6-hub` owns hosted incident truth and normalized crash work items
* `chummer6-hub-registry` enriches those incidents with release/install/update facts
* `fleet` may draft tests, repro attempts, patches, and PRs from normalized work
* `fleet` may emit internal release-smoke crash packets from controlled verification hosts when a built desktop head fails to start

Forbidden shape:

* raw client crash traffic flowing straight to Fleet as the primary seam
* Fleet merging or releasing a fix solely because crash automation proposed it
* promoting a desktop head whose startup smoke failed or crashed
* user-visible repair bypassing registry-owned channel truth or UI-owned updater behavior

Crash fixes still ship through the standard review, publish, registry, and updater path.

## Karma Forge rule

Karma Forge and similar future variants are build axes, not pipeline homes.

Model them as:

* desktop head choice
* runtime-bundle head choice
* ruleset/profile compatibility
* registry-visible build dimensions

Do not move release ownership into Hub or Media Factory just because the matrix gets larger.

## Updater rule

Updater integration lives in `chummer6-ui`.

Release and channel truth for that updater lives in `chummer6-hub-registry`.

Fleet may orchestrate the packaging/promotion wave, but the desktop head owns the updater client behavior and the registry owns the published feed/channel records.

## Latest shelf rule

The public `/downloads` surface is a latest-build shelf, not a long archive listing.

When the desktop build pipeline is configured with a deploy target, each successful build must:

* publish the freshly generated bundle into the active downloads root
* replace the compatibility and canonical release manifests in that root
* remove superseded desktop artifacts from that root

That keeps `chummer.run/downloads` and other self-hosted downloads surfaces aligned to the newest successful desktop bundle.
