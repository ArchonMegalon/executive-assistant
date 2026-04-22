# Public downloads policy

## Purpose

This file defines the public copy and shelf rules for `/downloads`.

The downloads surface is a proof shelf first:

* one current recommended install path
* honest platform coverage
* clear release posture
* no archive-collector framing on the front path

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
* show channel and version clearly
* separate installer media from advanced fallback assets
* explain when a platform is not currently available
* keep public copy aligned with registry truth and landing copy
* lead with the Terminal install-command handoff on macOS whenever unsigned-preview policy makes downloaded scripts or raw DMGs the wrong primary path

The public shelf must not:

* read like a raw artifact bucket
* bury the recommended build beneath archives
* imply sign-in is required for open public installers
* pretend portable archives are the default when canon says installer-first

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
* whether it is preview or stable
* what platforms are supported today
* when the user should expect in-app updates versus reinstall/install handoff
* when macOS begins with a Terminal command because that is the safest unsigned-preview path

Download-facing copy must not say:

* per-user installer
* personalized build
* instant fix availability from merged code
* auto-update guarantees that outrun registry or UI truth
* tell users to double-click an unsigned downloaded `.command` when the actual supported path is a copy-paste Terminal command

## Ownership

* `chummer6-design` owns the copy and shelf policy.
* `chummer6-hub` owns the hosted `/downloads` projection.
* `chummer6-hub-registry` owns release, channel, compatibility, and artifact truth.
* `chummer6-ui` owns installer-ready desktop outputs and local updater behavior.
* `fleet` may publish the generated shelf inputs, but it does not become the meaning authority.
