# Public downloads policy

## Purpose

This file defines the public copy and shelf rules for `/downloads`.

The downloads surface is a proof shelf first:

* one current recommended install path
* honest platform coverage
* clear release posture
* no archive-collector framing on the front path

## Download authority

`chummer.run` is the only official client download source.

Build artifacts, installers, archives, update payloads, and preview clients must not be published directly to GitHub releases, GitHub Actions artifacts, repo attachments, or other repo-hosted binary shelves as an end-user download path. GitHub may host source, issues, and development evidence, but public acquisition must route through `chummer.run` download or install handoff surfaces backed by registry release truth.

## CTA labels

Allowed primary CTA labels include:

* `Create account to install`
* `Install the current preview`
* `Download for Windows`
* `Download for Linux`
* `Open Mac install command`

Forbidden primary labels include:

* `Get the latest drop`
* `Grab everything`
* `Nightly`
* vague internal build terms

## Shelf rules

The public shelf must:

* lead with one recommended build per supported platform
* serve official client downloads only from `chummer.run` routes backed by registry truth
* show channel and version clearly
* separate installer media from advanced fallback assets
* distinguish posted proof from whole-product flagship status
* keep artifact-factory explainers, packet siblings, and proof-gallery links subordinate to the posted install shelf instead of treating them as equivalent route authority
* explain when a platform is not currently available
* keep public copy aligned with registry truth and landing copy
* lead with the Terminal install-command handoff on macOS whenever unsigned-preview policy makes downloaded scripts or raw DMGs the wrong primary path
* label secondary heads, archives, and manual packages as fallback or recovery paths when they are not the primary route
* keep proof cards, captions, preview explainers, and artifact-gallery links visually secondary to the install shelf itself
* keep any concierge widget in explicit preview-overlay posture with the recommended first-party download still visible as the fixed route
* name recovery routes as help, relinking, or escalation paths rather than implying the widget repaired the install
* follow `ARTIFACT_SHELF_POLICY.md` whenever proof-gallery artifacts, captions, or packet siblings appear beside install truth so audience, locale, retention, and inspectable-source posture stay visible

The public shelf must not:

* read like a raw artifact bucket
* send users to GitHub releases, GitHub Actions artifacts, or repo-hosted binaries to download the client
* bury the recommended build beneath archives
* imply sign-in is required for open public installers
* pretend portable archives are the default when canon says installer-first
* let artifact previews or proof cards read like the recommended install path
* let artifact-factory cards, packet siblings, or proof-gallery bundles become the authority over what someone should download first
* let preview proof wording imply whole-product flagship status
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
* what current proof actually covers
* what platforms are supported today
* whether a second app or package is fallback-only
* whether a route is the recommended install path, an inspectable proof artifact, or a bounded fallback/recovery path
* when the user should expect in-app updates versus reinstall/install handoff
* when macOS begins with a Terminal command because that is the safest unsigned-preview path
* that any concierge helper on the page is an optional preview overlay rather than the release authority

Download-facing copy must not say:

* per-user installer
* personalized build
* download from GitHub
* instant fix availability from merged code
* auto-update guarantees that outrun registry or UI truth
* tell users to double-click an unsigned downloaded `.command` when the actual supported path is a copy-paste Terminal command
* call a preview lane flagship-complete unless `FLAGSHIP_RELEASE_ACCEPTANCE.yaml` is actually satisfied
* present fallback apps or archive packages as equal defaults when the primary shelf route is different
* let artifact-factory output, proof screenshots, or explainer bundles read like substitute release authority for the posted install shelf
* let proof-gallery or packet-detail routes blur the difference between an inspectable artifact and the actual recommended download route

## Ownership

* `chummer6-design` owns the copy and shelf policy.
* `chummer6-hub` owns the hosted `/downloads` projection.
* `chummer6-hub-registry` owns release, channel, compatibility, and artifact truth.
* `chummer6-ui` owns installer-ready desktop outputs and local updater behavior.
* `fleet` may publish the generated shelf inputs, but it does not become the meaning authority.
