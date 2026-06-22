# Public downloads policy

## Purpose

This file defines the public copy and shelf rules for `/downloads`.

The downloads surface is a download shelf first:

* one current recommended install path
* honest platform coverage
* clear release posture
* no archive-collector framing on the front path
* no public portable-build framing when an installer or package lane exists

## Download authority

`chummer.run` is the only official client download source.

Build artifacts, installers, archives, update payloads, and preview clients must not be published directly to GitHub releases, repository automation artifacts, repo attachments, or other repo-hosted binary shelves as an end-user download path. GitHub may host source, issues, and development records, but public acquisition must route through `chummer.run` download or install handoff surfaces backed by the release registry.

## CTA labels

Allowed primary CTA labels include:

* `Nightly`
* `Stable`
* `Claim your copy`
* `Open Mac support`
* `Download for Windows`
* `Download for Linux`
* `Install on Arch`

Forbidden primary labels include:

* `Get the latest drop`
* `Grab everything`
* vague internal build terms

## Shelf rules

The public shelf must:

* lead with one recommended build per supported platform
* show visible `Nightly` and `Stable` lane buttons when both lanes are published
* serve official client downloads only from `chummer.run` routes backed by the release registry
* show channel and version clearly
* keep public installer/package lanes separate from support-only fallback assets
* keep advanced release records away from the normal install choice
* explain when a platform is not currently available
* keep public copy aligned with registry truth and landing copy
* keep macOS off the normal public shelf until there is a normal public Mac installer
* label secondary heads, archives, and manual packages as support-only paths when they are not the primary route
* keep any concierge widget in explicit preview-overlay posture with the recommended first-party download still visible as the fixed route
* name recovery routes as help, relinking, or escalation paths rather than implying the widget repaired the install

The public shelf must not:

* read like a raw artifact bucket
* send users to GitHub releases, repository automation artifacts, or repo-hosted binaries to download the client
* bury the recommended build beneath archives
* imply sign-in is required for open public installers
* pretend portable archives are the default when canon says installer-first
* expose portable builds on the normal public shelf
* let media previews, status records, or support packages read like the recommended install path
* let concierge phrasing turn a fallback, portable, or support-directed package into the default CTA
* let a widget ask for claim codes, auth secrets, or private support identifiers

## Guest versus linked copy

Public stable or preview installers may remain guest-readable when the access class is open.

Signed-in copy may add:

* account-aware install guidance
* claim-ticket creation
* support-history and fix-status linkage

That is relationship context, not a different binary.

## Copy discipline

Download-facing copy must say:

* what the build is
* what channel it belongs to
* that the official client download or install handoff starts from `chummer.run`
* whether it is preview or stable
* what platforms are supported today
* whether a second app or package is fallback-only
* when an Arch/AUR package is available or still pending
* whether a route is the recommended install path or a support/recovery path
* when the user should expect in-app updates versus reinstall/install handoff
* that any concierge helper on the page is an optional preview overlay rather than the release authority

Download-facing copy must not say:

* per-user installer
* personalized build
* download from GitHub
* portable as the normal public route
* instant fix availability from merged code
* auto-update guarantees that outrun registry or UI truth
* call a nightly lane flagship-complete unless `FLAGSHIP_RELEASE_ACCEPTANCE.yaml` is actually satisfied
* present fallback apps or archive packages as equal defaults when the primary shelf route is different
* let media output, screenshots, or explainer bundles read like substitute release authority for the posted install shelf

## Ownership

* `chummer6-design` owns the copy and shelf policy.
* `chummer6-hub` owns the hosted `/downloads` projection.
* `chummer6-hub-registry` owns release, channel, compatibility, and artifact truth.
* `chummer6-ui` owns installer-ready desktop outputs and local updater behavior.
* `fleet` may publish the generated shelf inputs, but it does not become the meaning authority.
