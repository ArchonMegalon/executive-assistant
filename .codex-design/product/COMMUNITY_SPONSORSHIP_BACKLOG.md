# Community Sponsorship Backlog

Purpose: capture the Hub-first community sponsorship wave as executable canon instead of leaving it spread across audits, feedback notes, and partial implementation assumptions.

## Canonical split

* `chummer6-hub` owns the product plane: user accounts, generic groups, memberships, join/boost codes, fact ledger, reward journal, entitlement journal, participation UX, and receipt-derived community projections.
* `fleet` owns the execution plane: dynamic participant lanes, lane-local device-auth execution, worker lifecycle, mission telemetry, and signed contribution receipts.
* `executive-assistant` owns provider/lane telemetry and synthesis support, not community product truth.

## Current state

The architecture is already materially in place.

Landed v1 surfaces:

* Hub already exposes account, group, boost-code, sponsor-session, ledger, leaderboard, and entitlement contracts plus controllers and services.
* Hub already ingests Fleet contribution receipts and projects sponsor-session / group contribution state.
* Fleet already supports participant burst lanes, lane-local device auth, dynamic participant-lane control APIs, sponsor metadata, and signed receipt emission.
* EA already projects sponsor ownership metadata through provider and responses telemetry.

The next wave is therefore not a fresh architecture rewrite. It is a convergence and hardening wave:

* durable Hub community storage instead of process-local demo state
* one participation-intent story on top of the community spine instead of parallel intent models
* richer community/product surfaces built on the same user/group/ledger substrate

## Product rules

* Do not build one-off Fleet-side guided-contribution product logic ahead of the Hub community/accounting spine.
* Do not collapse raw identity subjects into product users.
* Do not special-case guided-contribution groups when the system really needs generic `group_type` plus capability flags.
* Do not collapse facts, rewards, and entitlements into one table or one DTO family.
* Do not mint rewards from mere auth completion or idle time; mint from validated Fleet receipts.
* Do not store raw participant `auth.json` or device-auth secrets in Hub.
* Do not let sponsored premium workers bypass `jury` landing authority.

## P0 backlog

### HUB-P0-01

Task: harden the product-level user layer above identity.

Status:
`v1 landed`, `remaining delta = persistence and richer profile management`

Landed now:

* `AccountContracts.cs`
* `AccountsController.cs`
* `AccountService.cs`

Remaining delta:

* durable storage for users, profiles, and linked principals
* richer profile controls for visibility, timezone, locale, and future community preferences
* explicit migration path from local durable store to eventual database-backed persistence if/when needed

Acceptance:

* product users survive restarts
* user profile truth remains distinct from raw identity-session truth

### HUB-P0-02

Task: keep the generic group system canonical.

Status:
`v1 landed`, `remaining delta = role/capability depth`

Landed now:

* `GroupContracts.cs`
* `GroupsController.cs`
* `GroupMembershipsController.cs` equivalent behavior folded into group/membership APIs
* `GroupService.cs`
* join-code and boost-code handling on the community plane

Remaining delta:

* durable storage for groups, memberships, roles, and join codes
* richer role templates for `guided_contribution`, `campaign`, `gm_circle`, `creator_team`, and future org-like groups
* stronger capability-matrix enforcement beyond the current default capability set

Acceptance:

* groups survive restarts
* group behavior stays data-driven instead of contribution-only

### HUB-P0-03

Task: keep the three-layer ledger durable and explicit.

Status:
`v1 landed`, `remaining delta = durable storage and projection hardening`

Landed now:

* `LedgerContracts.cs`
* `EntitlementContracts.cs`
* `LeaderboardContracts.cs`
* `LedgerController.cs`
* `LeaderboardsController.cs`
* `EntitlementsController.cs`
* reward and entitlement derivation from receipts

Remaining delta:

* durable storage for fact ledger, reward journal, entitlement journal, badges, and leaderboard snapshots
* stronger projection fingerprints / replay safety for leaderboard and entitlement views
* explicit moderation/reversal path for reward corrections

Acceptance:

* receipts, rewards, and entitlements survive restarts
* the three ledgers remain visibly separate

### HUB-P0-04

Task: converge participation UX onto the community spine.

Status:
`partially landed`

Landed now:

* Hub already serves participation/account/group/leaderboard/reward HTML surfaces directly from `Chummer.Run.Api`.
* Hub already bridges to Fleet for sponsor-session device-auth and lane control.

Remaining delta:

* the public participation flow must resolve to the same sponsor-session / community-ledger spine instead of maintaining a parallel intent-only state model
* the generic participation route language should stay compatible with sponsor-session semantics
* the UI shell can remain thin/server-rendered, but the data path must be canonical

Acceptance:

* one public participation flow exists
* it writes through the reusable user/group/ledger platform

### HUB-P0-05

Task: keep the sponsorship/guided-contribution workflow as the first use case of the community platform.

Status:
`v1 landed`, `remaining delta = durability and richer campaign semantics`

Landed now:

* boost campaigns
* boost codes
* sponsor sessions
* Fleet bridge handoff

Remaining delta:

* durable campaign/code/session storage
* richer campaign metadata, visibility, and seasonal framing

Acceptance:

* sponsorship survives restarts and remains a reusable workflow rather than a one-off side table

### HUB-P0-06

Task: keep AI-side receipt ingest and sponsor-session projections canonical.

Status:
`v1 landed`

Landed now:

* `BoosterReceiptsController.cs`
* sponsor-session projection and group leaderboard projection surfaces

Remaining delta:

* no new architecture required; only hardening and projection depth as product needs grow

Acceptance:

* Hub remains the canonical community ledger owner
* Fleet remains an evidence emitter, not the reward ledger

### FLEET-P0-01

Task: preserve the cheap-first execution plane while keeping dynamic participant lanes available.

Status:
`v1 landed`

Landed now:

* participant burst policy in Fleet project config
* dynamic participant-lane control API
* device-auth helper
* participant worker launcher
* signed contribution receipt emission
* sponsor metadata in lane state

Remaining delta:

* no immediate new Fleet product behavior is required for this wave
* Fleet work should follow Hub durability/convergence work, not outrun it

Acceptance:

* Fleet stays the worker/execution plane
* Fleet does not become the product community ledger

### EA-P0-01

Task: keep sponsor attribution visible in provider/lane telemetry without absorbing community ownership.

Status:
`v1 landed`

Landed now:

* provider telemetry and responses surfaces already project sponsor/user/group ownership fields

Remaining delta:

* only additive telemetry refinement when Fleet or Hub needs richer attribution

Acceptance:

* EA remains provider-aware substrate and telemetry plane, not the community product shell

## P1 backlog

### HUB-P1-01

Task: deepen leaderboards, badges, contribution feed, and public/private identity controls.

Target outcomes:

* individual, group, and seasonal leaderboards
* badge and founder/founding-wave recognition
* contribution feed tied to landed work
* pseudonymous/public visibility controls

### HUB-P1-02

Task: add quests and roadmap-linked campaigns.

Target outcomes:

* weekly/monthly quests
* group goals
* roadmap-linked campaign progress bars
* milestone-aware sponsor campaigns

### HUB-P1-03

Task: add moderation/reversal tooling for reward and entitlement corrections.

Target outcomes:

* reward reversal path
* badge correction path
* entitlement revoke/grant audit path

### HUB-P1-04

Task: turn claimed installs into a roaming workspace backed by the existing account, campaign, and entitlement spine.

Target outcomes:

* person, campaign, and group-scoped workspace restore
* rule-environment refs instead of ad hoc house-rule blobs
* artifact-shelf restore by manifest or reference
* capability grants instead of synced premium flags
* explicit device-handoff conflict choices instead of silent last-write-wins

## P2 backlog

### HUB-P2-01

Task: reuse the same group and entitlement platform for GM circles and campaign rosters.

Target outcomes:

* `gm_circle` and `campaign` group types
* private group dashboards
* campaign roster authority
* group-owned premium / GM entitlements

### HUB-P2-02

Task: move supporter/premium features onto entitlement-backed gates.

Target outcomes:

* supporter flair
* early access / beta access
* GM tool unlocks
* reserved vanity handles or similar social perks

### HUB-P2-03

Task: build first-class organizer and campaign operator surfaces on top of the same group, campaign, and entitlement substrate.

Target outcomes:

* campaign workspace and roster authority
* GM circles and campaign operator dashboards
* runboards, readiness checks, and rule-environment health
* group-owned feature posture without a second authority model

### FLEET-P2-01

Task: support group-owned premium burst quotas only after Hub entitlements are mature.

Target outcomes:

* sponsor caps per group
* campaign quotas
* moderation/reversal support

## Immediate execution order

1. close durable Hub community storage
2. converge public participation onto the canonical sponsor-session/community-ledger path
3. keep Fleet stable except for compatibility needed by the Hub-owned product plane
4. grow P1 social/gamified features only after the durable P0 substrate is honest
