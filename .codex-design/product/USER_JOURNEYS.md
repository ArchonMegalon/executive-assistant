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

`FLAGSHIP_PRODUCT_BAR.md` defines the craftsmanship bar for those journeys.
`FLAGSHIP_RELEASE_ACCEPTANCE.yaml` defines the release-ready proof that the journeys feel flagship grade rather than merely mapped.

## Build

Goal: create or refine a runner without mystery math.

Flagship bar:

* one obvious primary builder path per supported head
* authored SR4, SR5, and SR6 labels and cues where the rules diverge
* active drugs, effects, legality, and timed state visible before commit
* active ruleset, preset, and amend-package posture visible before a user trusts the build
* compare and inspect flow stays comfortable under dense expert data

Canonical detail:

* `journeys/build-and-inspect-a-character.md`
* `BUILD_LAB_PRODUCT_MODEL.md`

## Explain

Goal: understand why a number, legality result, or tradeoff changed.

Flagship bar:

* explain answers read like product truth rather than debug output
* important deltas cite the responsible source, rule, or effect chain
* explain can name the active rule environment and the package change that altered the outcome
* imports surface parity drift explicitly instead of silently normalizing it

Canonical detail:

* `journeys/build-and-inspect-a-character.md`
* `BUILD_LAB_PRODUCT_MODEL.md`
* `CHARACTER_LIFECYCLE_AND_LIVING_DOSSIER.md`

## Run

Goal: keep the same runner, crew, campaign, and recent workspace alive across live play, claimed-device handoff, reconnect, and recovery.

Flagship bar:

* reconnect and resume are trustworthy under table pressure
* live, stale, offline, pending, and conflict posture are visually obvious
* missing or incompatible rule packs and amend packages are explicit before a resumed device computes against the wrong environment
* player, GM, and observer flows feel authored for live play rather than recycled workbench layouts
* finding a table, passing community-rule preflight, and getting into the right session space are part of the same trustworthy run journey

Canonical detail:

* `CAMPAIGN_WORKSPACE_AND_DEVICE_ROLES.md`
* `ROAMING_WORKSPACE_AND_ENTITLEMENT_SYNC.md`
* `journeys/continue-on-a-second-claimed-device.md`
* `journeys/rejoin-after-disconnect.md`
* `journeys/recover-from-sync-conflict.md`
* `journeys/run-a-campaign-and-return.md`
* `CAMPAIGN_SPINE_AND_CREW_MODEL.md`
* `WORLD_STATE_AND_MISSION_MARKET_MODEL.md`
* `OPEN_RUNS_AND_SHADOWCASTERS_NETWORK.md`
* `SEATTLE_OPEN_RUN_001_VERTICAL_SLICE.md`

## Publish

Goal: turn grounded dossiers, packets, and recaps into finished artifacts without losing provenance.

Flagship bar:

* preview-before-publish remains obvious where required
* artifact polish is strong enough for public sharing, not only internal export
* published artifacts keep the rule-environment and compatibility context needed to trust what was published
* provenance and compatibility remain attached without cluttering the primary publishing path

Canonical detail:

* `journeys/publish-a-grounded-artifact.md`
* `CHARACTER_LIFECYCLE_AND_LIVING_DOSSIER.md`
* `WORLD_STATE_AND_MISSION_MARKET_MODEL.md`

## Join

Goal: find the right table, prove fit, schedule it cleanly, and arrive with the right runner and expectations.

Flagship bar:

* a player can see the active community rule environment before applying
* preflight explains pass, warn, fail, or blocked instead of silently gatekeeping
* quickstart runners are good enough for real table entry, especially on mobile
* Discord, Teams, and VTTs remain projection lanes instead of becoming Chummer truth

Canonical detail:

* `journeys/find-and-join-an-open-run.md`
* `OPEN_RUNS_AND_SHADOWCASTERS_NETWORK.md`
* `COMMUNITY_RULE_ENVIRONMENTS_AND_APPROVAL.md`
* `RUN_APPLICATION_PREFLIGHT_MODEL.md`
* `QUICKSTART_RUNNER_AND_PREGEN_FLOW.md`
* `SESSION_ZERO_AND_TABLE_CONTRACT_MODEL.md`
* `SEATTLE_OPEN_RUN_001_VERTICAL_SLICE.md`

## Improve

Goal: report pain, follow closure, and trust whether the product actually got better.

Flagship bar:

* crash, bug, feedback, and support routes are reachable from the product when users need them
* public shelf, help, status, and in-product fix messaging never contradict each other
* recovery guidance tells the user the next safe action instead of only exposing system state

Canonical detail:

* `journeys/install-and-update.md`
* `journeys/claim-install-and-close-a-support-case.md`
* `journeys/organize-a-community-and-close-the-loop.md`
* `PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md`
* `SUPPORT_AND_SIGNAL_OODA_LOOP.md`

## Rule

If a repo changes one of these cross-head journeys, it must update the detailed journey doc and this top-level map before implementation lands.
If a release claim depends on these journeys, the same change must keep `FLAGSHIP_RELEASE_ACCEPTANCE.yaml` and `METRICS_AND_SLOS.yaml` honest.
