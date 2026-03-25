# User journeys

## Purpose

This file is the top-level product map for the journeys users actually live inside.

The detailed happy-path and failure-mode canon still lives under `journeys/*.md`.
This file keeps the center of gravity legible as one product story:

* Build
* Explain
* Run
* Publish
* Improve

## Build

Goal: create or refine a runner without mystery math.

Canonical detail:

* `journeys/build-and-inspect-a-character.md`
* `BUILD_LAB_PRODUCT_MODEL.md`

## Explain

Goal: understand why a number, legality result, or tradeoff changed.

Canonical detail:

* `journeys/build-and-inspect-a-character.md`
* `BUILD_LAB_PRODUCT_MODEL.md`
* `CHARACTER_LIFECYCLE_AND_LIVING_DOSSIER.md`

## Run

Goal: keep the same runner, crew, campaign, and recent workspace alive across live play, claimed-device handoff, reconnect, and recovery.

Canonical detail:

* `ROAMING_WORKSPACE_AND_ENTITLEMENT_SYNC.md`
* `journeys/continue-on-a-second-claimed-device.md`
* `journeys/rejoin-after-disconnect.md`
* `journeys/recover-from-sync-conflict.md`
* `journeys/run-a-campaign-and-return.md`
* `CAMPAIGN_SPINE_AND_CREW_MODEL.md`

## Publish

Goal: turn grounded dossiers, packets, and recaps into finished artifacts without losing provenance.

Canonical detail:

* `journeys/publish-a-grounded-artifact.md`
* `CHARACTER_LIFECYCLE_AND_LIVING_DOSSIER.md`

## Improve

Goal: report pain, follow closure, and trust whether the product actually got better.

Canonical detail:

* `journeys/install-and-update.md`
* `journeys/claim-install-and-close-a-support-case.md`
* `journeys/organize-a-community-and-close-the-loop.md`
* `PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md`
* `SUPPORT_AND_SIGNAL_OODA_LOOP.md`

## Rule

If a repo changes one of these cross-head journeys, it must update the detailed journey doc and this top-level map before implementation lands.
