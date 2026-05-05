# Campaign workspace and device roles

## Purpose

This file defines how Chummer's signed-in home and campaign surfaces become operational workspaces instead of generic dashboards.

The product promise is:

> Chummer should tell the user what changed for them, what is safe to do next, which campaign or runner needs attention, and which device posture they are using for that job.

## Canonical principle

Campaigns are operational workspaces, not folders with extra tabs.

A workspace projection must compile from:

- campaign spine truth
- living-dossier continuity
- roaming workspace restore posture
- release and install truth
- support and closure truth
- artifact and publication references

A workspace projection must not become:

- a generic dashboard full of unrelated counters
- a repo-status wall leaking operator vocabulary
- a mystery cloud blob with no conflict semantics
- a local-only guess about release, entitlement, or support posture
- a second system of record that competes with campaign, install, or support truth

## Surface stack

The workspace model has four user-facing layers.

### 1. Home cockpit

The signed-in home surface is the first proof that Chummer understands the user's real situation.

It must be able to project:

- continue this runner
- continue this campaign
- this campaign changed rules
- this install is on `Stable`, `Preview`, or another explicit channel posture
- this install has role `workstation`, `play_tablet`, `observer_screen`, `travel_cache`, or `preview_scout`
- this issue you reported is fixed on your real channel
- this artifact, recap packet, or publication output is ready
- this campaign, install, or support state needs attention before you continue

The home cockpit should answer **"what changed for me?"** before it answers **"what version exists?"**

### 2. Campaign workspace

A campaign workspace is the operational center for one crew or campaign.

It must carry:

- campaign identity and current roster
- active rule-environment posture
- dossier freshness and stale-state cues
- downtime plan, aftermath summary, and next-session return actions
- heat movement, faction pressure, contact truth, and reputation cues with visible reasons
- session-start readiness summary
- GM-ready runboard
- world pressure overview and mission-market opportunities
- recent recap and artifact shelf
- unresolved restore, sync, or continuity conflicts
- support or known-issue cues that affect this campaign or the active install

The campaign workspace is where a user should regain context after time away. It is not only a list of runners or runs.

### 3. Runboard / session board

A runboard is the live operational slice of the campaign workspace.

It may project:

- current run and scene
- objectives and blockers
- mission packet candidates
- runner readiness and missing prerequisites
- rule-environment mismatches that matter before play resumes
- observer-safe or player-safe views depending on install role
- recap-safe notes and publication-safe outputs derived from the same continuity spine

For future horizons, the runboard may also expose:

- mission packets awaiting GM adoption into campaign continuity
- city/district pressure deltas linked to approved outcomes
- explicit why a packet cannot be adopted due to approvals or policy

The runboard may be rendered differently on desktop, mobile, or observer installs, but it must compile from the same campaign truth.

### 4. Workspace rail

Every claimed install should show a compact workspace rail or equivalent posture cue.

That rail should make visible:

- current install role
- current channel posture
- offline or reconnect posture
- unresolved conflicts or stale data
- whether this install is affected by an open case or known issue
- the next safe recovery or update action

## Required workspace projections

The minimum first-wave projection set is:

### Continue card

Shows the most likely safe next action:

- continue runner
- resume campaign
- return to compare/repair
- reopen the latest support case status

### What-changed-for-me packet

For one user, one install, and one moment in time, Chummer must be able to say:

- what changed since last use
- why it changed
- which downtime, aftermath, heat, faction, contact, or reputation changes need attention
- whether it is safe to proceed
- what the next safe action is

This packet matters more than a raw notification count.

### Campaign memory packet

For the active campaign, Chummer must be able to project one governed campaign-memory packet that keeps the return loop legible.

That packet should make visible:

- downtime actions that are ready, blocked, or waiting on another actor
- aftermath facts that changed runner, crew, or campaign posture
- heat channels and threshold changes that alter risk
- faction stance changes that matter to the next job or current obligations
- contact truth changes such as favors owed, access unlocked, availability loss, compromise, or new asks
- reputation movement and any follow-on spend or fallout cues

This packet is first-class workspace truth.
It must not degrade into diary prose, detached recap cards, or local sticky notes on one device.

### Readiness summary

For the active campaign or run, Chummer should summarize:

- which runner or dossier is stale
- which rule environment is missing or changed
- whether the current install can safely continue
- which role-specific affordances are available on this device

### Trust rail

Workspace surfaces must expose visible trust cues for:

- why a number changed
- why a build or dossier is stale
- why a rule environment no longer matches
- why this install should not update yet
- why a support case is still open
- why a fix notice is real for this user and this channel

### Publication shelf

Home and campaign workspaces may expose:

- dossier packets
- recap cards
- campaign cold-open cards
- mission briefings
- evidence rooms
- primers
- other publication-safe artifacts

Those outputs remain downstream of provenance-bearing truth. They do not become continuity truth themselves.
Campaign cold-open and mission-briefing launches are first-class workspace promises only when they carry visible audience, locale, and source-pack posture instead of behaving like detached media links.
Campaign-facing shelves also follow `ARTIFACT_SHELF_POLICY.md` so retention posture, safer audience fallback, and inspectable source actions stay visible when recap, primer, or briefing cards appear in workspace rails.

## Device roles

Device roles are install-local posture, not person truth, entitlement truth, or campaign truth.

A user may own several claimed installs with different roles at the same time.

### `workstation`

Primary build, compare, moderation, publication, and operator surface.

Expected posture:

- richest authoring and compare tooling
- broadest local cache
- strongest repair and inspection affordances
- optional preview-channel participation when explicitly chosen

### `play_tablet`

Fast resume and session-safe field device.

Expected posture:

- continuity-first home surface
- travel-safe caching and reconnect posture
- fewer high-risk authoring affordances during live play
- stronger runboard and readiness emphasis than build tooling

### `observer_screen`

Read-mostly or presentation-first install.

Expected posture:

- recap, runboard, or spectator-safe projections
- minimal authoring authority
- explicit dependence on hosted or nearby truth
- easy mode switching between player-safe and observer-safe views where allowed

### `travel_cache`

Offline or low-connectivity posture for a claimed device.

Expected posture:

- pinned campaign and runner continuity
- explicit prefetch state
- louder stale-state and repair cues
- clear visibility when reconnect or update is needed before trusting broader state

### `preview_scout`

A spare install that tries preview or guided lanes earlier than the main machine.

Expected posture:

- clearer warning language
- install-local preview posture that does not bleed into other installs
- easy path back to the conservative install for real play

## Role rules

- Device role is chosen per install and may change later, but changes must be explicit.
- Changing a device role must not silently change account entitlements, campaign membership, or other installs.
- Per-install channel posture must remain visible when one claimed device is on `Preview` and another stays on `Stable`.
- Role-specific default affordances are allowed; role-specific truth forks are not.
- If a role cannot safely perform the requested action, the product must explain the recovery or handoff path instead of pretending the action succeeded.

## Audience overlays

Device roles are not the same thing as audience roles.

The same `workstation` may be used by:

- a player who mainly builds and reviews
- a GM who needs runboard and rule-environment authority
- an organizer who also needs community and support closure posture
- a creator who publishes packets and primers

Audience overlays may change what is emphasized on a workspace, but they must reuse the same underlying campaign, install, support, and artifact truth.

Audience overlays also gate campaign artifact launch:

- `campaign_joiner` and `player_safe` cold-opens may appear on shared campaign home surfaces
- `mission_briefing` defaults to the player-safe variant on general campaign surfaces
- `gm_only` briefing variants require explicit authority and must not leak through device-role shortcuts
- locale fallback may change presentation language, but it may not change audience or spoiler class

## State model

Every home cockpit and campaign workspace should be able to fall into a bounded visible state such as:

- healthy
- attention_needed
- blocked_before_play
- offline_but_usable
- restore_conflict_present
- rule_environment_mismatch
- update_available
- support_closure_pending
- preview_diverged

A workspace may carry more than one cue, but the product must still surface one recommended next safe action.

## Contract posture

This file does not define final DTOs, but it does define the projection families the product needs.

### `Chummer.Campaign.Contracts`

Should be able to project:

- `WorkspaceSummary`
- `CampaignWorkspaceSummary`
- `CampaignMemorySummary`
- `RosterReadinessSummary`
- `DossierFreshnessCue`
- `RuleEnvironmentHealthCue`
- `RunboardSummary`
- `ContinuityConflictCue`
- `DowntimeActionCue`
- `AftermathChangeCue`
- `HeatLedgerCue`
- `FactionStandingCue`
- `ContactTruthCue`
- `ReputationCue`
- `NextSessionReturnAction`
- `RecapShelfEntry`
- `WorldPressureCue`
- `MissionMarketSummary`

### `Chummer.Control.Contracts`

Should be able to project:

- `SupportClosureCue`
- `KnownIssueAffectingInstall`
- `DecisionNotice`
- `NextSafeActionCue`

### `Chummer.Hub.Registry.Contracts`

Should be able to project:

- `InstallPostureSummary`
- `ChannelTruthSummary`
- `UpdateAffectingInstall`
- `ArtifactAvailabilitySummary`

These projections are not permission to move canonical ownership out of the owning repos.

## Authority split

### `chummer6-hub`

Owns:

- home cockpit and campaign workspace projections
- what-changed-for-me packets
- roster, rule-environment, dossier, and readiness summaries
- world pressure and mission-market projection summaries (future-adjacent)
- organizer and community operator posture built on the same group and entitlement substrate

### `chummer6-hub-registry`

Owns:

- install channel posture
- compatibility and update truth
- immutable artifact and publication references

### `chummer6-ui`

Owns:

- workstation cockpit UX
- compare, repair, readiness, and runboard surfaces on desktop
- device-role selection or local posture controls where exposed

### `chummer6-mobile`

Owns:

- play-tablet and travel-cache UX
- continuity-first resume behavior
- offline prefetch and reconnect posture

### `chummer6-core`

Owns:

- deterministic explainability
- rules and pack provenance
- compatibility inputs behind rule-environment health

### `chummer6-media-factory`

Owns:

- rendered publication outputs and previews

It does not own home-cockpit meaning, campaign workspace semantics, or readiness truth.

## Journeys and metrics handoff

This file compiles into and depends on:

- `ROAMING_WORKSPACE_AND_ENTITLEMENT_SYNC.md`
- `CAMPAIGN_SPINE_AND_CREW_MODEL.md`
- `USER_JOURNEYS.md`
- `journeys/continue-on-a-second-claimed-device.md`
- `journeys/run-a-campaign-and-return.md`
- `journeys/recover-from-sync-conflict.md`
- `journeys/organize-a-community-and-close-the-loop.md`
- `METRICS_AND_SLOS.yaml`

The most relevant release-gate promises are:

- `next_safe_action_clarity`
- `device_role_posture_visibility`
- `claimed_device_restore_candidate_fidelity`
- `campaign_and_dossier_continuity`
- `support_and_closure_honesty`

## Compounding loops

The point of these surfaces is to make the product's loops visible:

### Continuity loop

claim -> restore -> continue -> reconnect -> recap

### Confidence loop

inspect -> explain -> compare -> decide -> trust

### Closure loop

report -> cluster -> route -> release -> notify

### Output loop

dossier -> artifact -> recap -> primer -> publication

### Community loop

account -> group -> campaign -> entitlement -> operator surface

## Rules

- The first screen must answer "what changed for me?" before it answers "what version exists?"
- Campaign workspaces must expose rule-environment and dossier health before live play continues.
- Downtime, aftermath, heat, faction, contact, and reputation changes are first-class workspace truth, not optional recap garnish.
- Device roles are install-local posture and must not silently rewrite entitlements or campaign truth.
- A fix notice is only trustworthy when support and release truth agree it reached the reporter's real channel.
- Organizer and community operator surfaces must reuse the same account, group, and entitlement substrate rather than inventing a second authority model.
- Role-specific UX may hide unsafe affordances, but it must not hide state conflicts that affect trust.

## Non-goals

This file does not:

- replace `ROAMING_WORKSPACE_AND_ENTITLEMENT_SYNC.md`
- create a second campaign truth outside `Chummer.Campaign.Contracts`
- turn output artifacts into canonical continuity records
- require every install to look identical regardless of role
- force one workspace layout across desktop, mobile, and observer contexts
