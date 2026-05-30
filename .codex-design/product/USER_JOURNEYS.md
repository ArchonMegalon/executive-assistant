# User journeys

## Purpose

This file is the top-level product map for the journeys users actually live inside.

The detailed happy-path and failure-mode canon still lives under `journeys/*.md`.
This file keeps the center of gravity legible as one product story for the explainable campaign OS:

* Build
* Explain
* Run
* Publish
* Improve

`FLAGSHIP_PRODUCT_BAR.md` defines the craftsmanship bar for those journeys.
`FLAGSHIP_RELEASE_ACCEPTANCE.yaml` defines the release-ready proof that the journeys feel flagship grade rather than merely mapped.

## Flagship UX principle map

This is the cross-surface handoff contract for desktop, hub, and mobile.
Every promoted path must stay legible across four product promises:

| Principle | Product promise | Desktop/UI handoff | Hub/public handoff | Mobile/live handoff |
|---|---|---|---|---|
| Onboarding | The first real action is obvious, and fallback paths never masquerade as the default. | Install or open the workbench, then build or restore without browser ritual. | Downloads, account, status, and support all point at the same next safe action. | Join, rejoin, or resume starts from the live table state instead of a shrunk desktop ritual. |
| Safety | Users see rule, state, and consequence posture before they commit live work. | Ruleset, legality, explain, import drift, and publish-preview cues are visible before commit. | Community-rule preflight, release posture, and support boundaries stay explicit before users trust hosted copy. | Live, stale, offline, pending, and conflict posture are visible before a player or GM acts. |
| Closure | A finished action produces visible state change, receipt, or trustworthy completion copy. | Save, export, publish, and feedback flows end with a durable result instead of disappearing into silent success. | Public status, support follow-up, and publication truth describe the same closed-or-open state. | Session closeout, accepted roster changes, and recap-ready updates visibly land in campaign truth. |
| Recovery | Failure states always expose one next safe action and one bounded fallback. | Crash, update, restore, import, and sync-repair flows tell the user how to continue without guesswork. | Help, relinking, download, and support routes explain recovery without implying hidden operator magic. | Reconnect, replay, and conflict repair protect table continuity and explain what changed. |

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
* `CAMPAIGN_ADOPTION_WIZARD.md`
* `RUNNER_RESUME_AND_GOAL_PINS.md`

Journey handoff:

* Desktop/UI: land in the real builder with the active rule environment visible, then keep compare, explain, and save inside one dense workbench path.
* Hub/public: account, downloads, and support copy may point users into Build, but they must not invent a second builder truth or contradict the active install path.
* Mobile/live: quick edits stay bounded; when dense authoring is required, the mobile shell must hand back to the canonical builder without hiding what will change.

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
* `SOURCE_ANCHOR_AND_LOCAL_RULEBOOK_BINDING.md`

Journey handoff:

* Desktop/UI: explain opens where the user questions trust, with source anchors, active environment posture, and packet-backed deltas.
* Hub/public: hosted dossier, support, and publication surfaces may summarize explain truth, but they must point back to the same provenance-bearing packet.
* Mobile/live: quick explain stays lightweight, but warnings, stale state, and rule-environment drift must remain visible before a player or GM acts on it.

## Run

Goal: keep the same runner, crew, campaign, and campaign ledger alive across live play, claimed-device handoff, reconnect, and recovery.

Flagship bar:

* reconnect and resume are trustworthy under table pressure
* live, stale, offline, pending, and conflict posture are visually obvious
* missing or incompatible rule packs and amend packages are explicit before a resumed device computes against the wrong environment
* player, GM, and observer flows feel authored for live play rather than recycled workbench layouts
* finding a table, passing community-rule preflight, and getting into the right session space are part of the same trustworthy run journey
* the campaign ledger is a named first-class surface rather than hidden continuity glue
* combat turns, between-turn affordances, and GM action state are understandable without table folklore
* one approved run closeout can visibly change the campaign and world memory without hidden AI authority

Canonical detail:

* `CAMPAIGN_WORKSPACE_AND_DEVICE_ROLES.md`
* `ROAMING_WORKSPACE_AND_ENTITLEMENT_SYNC.md`
* `journeys/continue-on-a-second-claimed-device.md`
* `journeys/rejoin-after-disconnect.md`
* `journeys/recover-from-sync-conflict.md`
* `journeys/run-a-campaign-and-return.md`
* `CAMPAIGN_SPINE_AND_CREW_MODEL.md`
* `WORLD_STATE_AND_MISSION_MARKET_MODEL.md`
* `OPEN_RUNS_AND_COMMUNITY_HUB.md`
* `SEATTLE_OPEN_RUN_001_VERTICAL_SLICE.md`
* `LIVE_ACTION_ECONOMY_AND_TURN_ASSIST.md`
* `GM_RUNBOARD_LIVE_OPERATIONS.md`
* `PREP_PACKET_FACTORY_AND_PROCEDURAL_TABLES.md`
* `CREW_AND_MISSION_FIT_MODEL.md`
* `BLACK_LEDGER_MVP_001.md`

Journey handoff:

* Desktop/UI: campaign prep, GM operations, and ledger-facing actions must preserve the same campaign memory and rule-environment truth that live play consumes.
* Hub/public: find, join, schedule, account, and campaign surfaces must hand into the active session without losing roster, rule, or entitlement posture.
* Mobile/live: reconnect, replay, and conflict repair are first-class run paths, not exception copy around a happy path that only works on desktop.

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

Journey handoff:

* Desktop/UI: publish starts from grounded product truth and keeps preview, compatibility, and provenance visible before release.
* Hub/public: hosted publication, shelf, and follow-up routes must describe the same artifact state, preview posture, and compatibility story.
* Mobile/live: recap, dossier, and field-share moments can trigger Publish, but they must not bypass preview-first or provenance requirements.

## Join

Goal: find the right table, prove fit, schedule it cleanly, and arrive with the right runner and expectations.

Flagship bar:

* a player can see the active community rule environment before applying
* preflight explains pass, warn, fail, or blocked instead of silently gatekeeping
* quickstart runners are good enough for real table entry, especially on mobile
* Discord, Teams, and VTTs remain projection lanes instead of becoming Chummer truth

Canonical detail:

* `journeys/find-and-join-an-open-run.md`
* `OPEN_RUNS_AND_COMMUNITY_HUB.md`
* `COMMUNITY_RULE_ENVIRONMENTS_AND_APPROVAL.md`
* `RUN_APPLICATION_PREFLIGHT_MODEL.md`
* `QUICKSTART_RUNNER_AND_PREGEN_FLOW.md`
* `SESSION_ZERO_AND_TABLE_CONTRACT_MODEL.md`
* `SEATTLE_OPEN_RUN_001_VERTICAL_SLICE.md`
* `CREW_AND_MISSION_FIT_MODEL.md`

Journey handoff:

* Desktop/UI: full runner prep and preflight remediation stay available when a player needs to resolve fit before the table starts.
* Hub/public: discovery, community-rule preflight, scheduling, and account posture must flow into the session without hidden moderator-only steps.
* Mobile/live: accepted players can arrive, confirm expectations, and recover access from the device already at the table.

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
* `SUPPORT_PACKET_AND_CALCULATION_REPORT_UX.md`
* `PRODUCT_CONTROL_AND_GOVERNOR_LOOP.md`
* `SUPPORT_AND_SIGNAL_OODA_LOOP.md`

Journey handoff:

* Desktop/UI: crash, bug, update, and support entry points must preserve the context needed for closure without forcing users to retell the problem.
* Hub/public: status, support, known-issue, and fix messaging must describe one release truth and one next safe action.
* Mobile/live: interruption, reconnect failure, and table-impacting defects must route into support and recovery without losing the active campaign context.

## Rule

If a repo changes one of these cross-head journeys, it must update the detailed journey doc and this top-level map before implementation lands.
If a release claim depends on these journeys, the same change must keep `FLAGSHIP_RELEASE_ACCEPTANCE.yaml` and `METRICS_AND_SLOS.yaml` honest.
If a horizon or extension makes the story harder to explain than `build correctly, explain clearly, run reliably, recover calmly, carry the campaign forward`, the horizon is ahead of the product center of gravity.
