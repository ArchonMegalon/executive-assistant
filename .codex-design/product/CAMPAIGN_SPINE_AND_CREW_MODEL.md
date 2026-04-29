# Campaign spine and crew model

## Purpose

This file defines the missing middle of Project Chummer.

Chummer is not only:

* deterministic rules truth
* a character workbench
* a live session shell
* a publication surface

It is also a campaign-scale system with long-lived continuity.

That middle needs explicit canon for the things users actually carry across time:

* runner dossier
* crew
* campaign
* campaign memory and consequence truth
* rule environment
* run
* scene
* objective
* session event log
* continuity snapshot
* replay-safe recovery state

## Canonical domain objects

### Runner dossier

The long-lived representation of one runner as a person in motion, not only as a build result.

It may include:

* canonical build references
* active gear and lifestyle posture
* campaign role or crew role
* narrative-facing briefing data
* continuity and recap links

### Crew

A bounded group of runners that acts together inside one campaign or operation context.

Crew truth is not only chat membership and not only a Hub group.
It is a campaign-facing working set with role, availability, trust, and assignment meaning.

### Campaign

The long-lived operation frame that contains:

* crew membership or roster context
* active rule environment
* run history
* objectives
* continuity state
* recap and replay references

Campaign truth does not own shared-world strategy state.
Campaigns may reference mission-market identifiers and consequence markers, but those remain adjacent objects until a dedicated shared world contract is introduced.

### Campaign memory and consequence truth

Campaign memory is the governed continuity layer that lets a campaign survive the space between runs.

It carries first-class product truth for:

* downtime plans and queued downtime actions
* aftermath packages and explicit "what changed" receipts
* heat movement with named channels and threshold posture
* faction stance, favor, and consequence deltas that affect the crew now
* contact truth such as availability, leverage, debt, compromise, and relationship drift
* reputation gains, spends, burns, and next-session return cues

This is not recap prose and it is not only world-state flavor.
It is the durable campaign-scale consequence layer that desktop, mobile, Hub, and later publication projections must all reuse.

Campaign memory may reference world-facing identifiers, district pressure, or future BLACK LEDGER objects.
It still owns the campaign-local truth for what changed for this crew, what is stale, and what requires GM or player action before the next session.

### Run

A bounded operation or mission inside a campaign.

Runs may open and close, but their state must remain linkable to dossiers, scenes, outcomes, and publication artifacts.

### Scene

A bounded play or briefing context within a run.

It must be compatible with replay-safe event or checkpoint truth.

### Objective

The named intent or pressure the run is trying to satisfy.

Objectives may drive recap, artifact, and progress projections, but they must not become hand-authored fiction detached from receipts.

## Future adjacent objects

BLACK LEDGER introduces adjacent objects that sit next to this spine:

* `JobSeed`: a potential opportunity record sourced from world-state activity.
* `JobPacket`: a GM-curated mission packet that is distinct from a live campaign run.
* `ResolutionResult`: a campaign-consumption outcome record before a full world consequence step.

## Ownership split

### `chummer6-core`

Owns:

* deterministic mechanics
* explain receipts
* legality and reducer truth

Must not own:

* campaign identity
* crew meaning
* living-dossier history

### `chummer6-hub`

Owns:

* campaign spine truth
* crew and campaign identity
* run, scene, and objective continuity semantics
* replay-safe continuity projections that join build truth to hosted campaign history

This bounded context starts in Hub because Hub already owns the relationship and orchestration plane.
That does not make Hub a hidden owner of every middle-layer concern.

### `chummer6-mobile`

Owns:

* live session shell and continuity UX

Must not own:

* campaign semantics themselves

### `chummer6-ui`

Owns:

* workbench and dossier-facing authoring or inspection UX

Must not own:

* cross-head dossier or campaign truth

### `chummer6-media-factory`

Owns:

* rendered dossier, recap, packet, and publication assets

Must not own:

* campaign spine semantics

## Contract family

The first shared DTO family for this middle is `Chummer.Campaign.Contracts`.

It should carry:

* runner dossier identity and version refs
* crew and campaign identity
* campaign memory packet refs for downtime, aftermath, heat, faction, contact, and reputation truth
* rule-environment refs and compatibility fingerprints
* run, scene, and objective refs
* continuity snapshot refs
* replay-safe event or recap linkage
* next-session return action refs
* publication-safe dossier and recap projections

## Non-goals

This file does not:

* redefine engine legality or explain receipts
* define every UI screen
* turn media assets into campaign truth
* turn world-state strategy, district governance, or faction-seat control into campaign-owned truth
* require a new repo before the bounded context is real
