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
* run history
* objectives
* continuity state
* recap and replay references

### Run

A bounded operation or mission inside a campaign.

Runs may open and close, but their state must remain linkable to dossiers, scenes, outcomes, and publication artifacts.

### Scene

A bounded play or briefing context within a run.

It must be compatible with replay-safe event or checkpoint truth.

### Objective

The named intent or pressure the run is trying to satisfy.

Objectives may drive recap, artifact, and progress projections, but they must not become hand-authored fiction detached from receipts.

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
* run, scene, and objective refs
* continuity snapshot refs
* replay-safe event or recap linkage
* publication-safe dossier and recap projections

## Non-goals

This file does not:

* redefine engine legality or explain receipts
* define every UI screen
* turn media assets into campaign truth
* require a new repo before the bounded context is real
