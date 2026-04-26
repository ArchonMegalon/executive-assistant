# Campaign authority and permissions

## Purpose

This document defines campaign-level decision rights in one place for cross-repo
campaign, session, workspace, and publication control.

## Authority model

Campaign authority is scoped by role and artifact family:

* `Campaign` authority: who can edit or bind campaign identity, scope, state, and continuity.
* `Session` authority: who can change live or replay-safe run state.
* `Workspace` authority: who can change visible workspace artifacts (runboard, roster, notes, readiness).
* `Publication` authority: who can move an artifact from draft to discoverable.
* `Participation` authority: who can onboard, invite, and moderate organizer-facing group participation surfaces.

## Roles

* `Campaign Owner`: user that owns campaign account relationship and grants campaign roles.
* `Game Master`: designated organizer of a specific campaign session.
* `Player`: participant with runner authority.
* `Observer`: read-only participant in one campaign view.
* `Organizer / Community Operator`: campaign-facing community role used for participation and group operations.
* `World Operator`: capability holder for city/world frame governance within an approved organizer context.
* `Season Operator`: capability holder for season-level governance and season artifact controls.
* `Faction Seat`: delegated campaign-adjacent seat authority used to represent a stable political position.
* `Support`: Hub and Fleet support operators for escalation and case closure.
* `EA Operator`: EA-side execution/operator role for grounded automation and pilot operations.

## Decision rights

| Action family | Campaign Owner | Game Master | Player | Observer | Organizer / Operator | Support | EA Operator |
|---|---|---|---|---|---|---|---|
| Create, archive, transfer campaign | write | propose | no | no | no | no | no |
| Grant / revoke campaign and workspace roles | write | propose | no | no | propose | no | no |
| Add/remove roster members | write | write | no | no | no | no | no |
| Run start, stop, restart | no | write | no | no | no | no | no |
| Scene / objective transitions | no | write | no | no | no | no | no |
| Rule environment binding | write | propose | no | no | no | no | no |
| Recap, continuity checkpoint, return state | no | write | no | no | no | no | no |
| Campaign permission policy changes | write | no | no | no | no | no | no |
| Crash/support claim closure state | no | no | no | no | no | write | no |
| Publication promotion | no | propose | no | no | write | no | no |
| Evidence / receipt correction | no | propose | no | no | no | write | write |

### Future world-layer authority policy

The world layer is adjacent to the campaign lane and must never be treated as campaign truth.

Current policy:

* `World Operator`: can define and mutate `WorldFrame`-adjacent governance and mission-market policy, including seasonal/world-level packets and campaign-consumable mission opportunities.
* `Season Operator`: can adjust season-level parameters, pressure progression, and shared city cadence.
* `Faction Seat`: is a capability class, not a role. It does not imply campaign-owner or support authority and cannot bypass GM campaign authorization for a run.
* `World Operator`, `Season Operator`, and `Faction Seat` operate under explicit campaign-consent semantics:
  - campaign owners/GM must still authorize GM-run adoption of any world-seeded packet into a live campaign
  - campaign continuity facts remain unchanged unless replay-safe continuation rules allow the linkage
  - support/control truth stays in `Chummer.Control.Contracts`

### Future open-run and network authority policy

Open-run and Community Hub authority stays narrower than campaign truth:

* GMs own run listing, roster, and closeout decisions for one `OpenRun` unless an explicit organizer-curated mode says otherwise.
* Organizers may define visibility scope, season policy, and moderation policy, but they do not silently seize GM run truth.
* Organizers or community operators may publish `CommunityRuleEnvironment` and approval policy, but legality still derives from Chummer-owned rule-environment packages, amend packages, and approval receipts.
* Run-application preflight may recommend `pass`, `warn`, `fail`, or `blocked`, but it must expose readable reasons and next safe actions instead of hidden gatekeeping.
* External scheduling or meeting tools may project booking, links, or channel access. They do not own `RunPlan`, `OpenRun`, accepted roster, or outcome truth.
* VTTs and play surfaces may receive exported runner, opposition, or handout packets. They do not own roster, run, or consequence truth.
* GOD observer or debrief assistance requires explicit consent policy for that run; no operator may silently turn it on after roster lock.
* Reputation and seasonal-honor events must derive from typed source objects and visibility policy; Table Pulse or observer outputs may assist drafts but may not directly publish public scoring.

## Truth owner

* Campaign and roster truth: `chummer6-hub`
* Session and continuity truth: `chummer6-core`
* Workspace projection truth: `chummer6-ui` and `chummer6-mobile` from Hub projections
* Publication state: `chummer6-hub-registry`
* Support closure truth: `chummer6-hub` + `fleet`
* Automation output: `executive-assistant` only with explicit provenance requirements
* World and season governance truth (future): `chummer6-hub`

## Conflict rule

If two writers claim a conflicting truth for the same artifact scope:

1. Hub-owned campaign control blocks conflicting writes.
2. The dispute routes through `SUPPORT_AND_SIGNAL_OODA_LOOP.md`.
3. Manual conflict resolution requires explicit campaign-owner consent unless it is a safety rollback.

## Governance rule

Any design or code change that changes this matrix is a `Type E` change and must update:

* the relevant architecture and ownership docs
* acceptance in the active registry for the current wave
* the next post-audit or active wave plan impact route
