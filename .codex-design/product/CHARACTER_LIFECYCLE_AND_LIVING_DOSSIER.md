# Character lifecycle and living dossier

## Purpose

This file defines how a character stops being "just a build" and becomes a long-lived runner dossier inside Chummer.

The point is to keep one coherent story across:

* build
* explain
* run
* recover
* recap
* publish

## Lifecycle spine

### 1. Draft build

The runner is still a workbench-local draft.

Canonical truth:

* build composition
* deterministic legality
* explain receipts

### 2. Validated build

The runner has a canonical mechanics posture and can be trusted as a starting point.

This is still not the whole dossier.

### 3. Living dossier

The runner now has long-lived identity beyond the build sheet.

The dossier may carry:

* stable runner identity
* campaign and crew links
* rule-environment refs
* continuity and recovery links
* immutable snapshot and branch refs
* recap and publication-safe projections
* optional origin dossier canon and bounded media bundle refs

### 4. Session-active dossier

The dossier is now participating in a live run or scene.

Continuity must preserve:

* the last trusted state
* event or checkpoint linkage
* role and crew context

### 5. Recovery and recap dossier

The session may have ended, drifted, or partially failed.

The dossier must still support:

* replay-safe recovery
* after-action recap
* artifact-ready projection

### 6. Archived but rejoinable dossier

The dossier may become dormant without losing its campaign identity, role history, or evidence chain.

## Ownership split

### `Chummer.Engine.Contracts`

Owns:

* build legality
* explain receipts
* deterministic value truth

### `Chummer.Campaign.Contracts`

Owns:

* dossier identity
* crew and campaign linkage
* continuity state
* recap-safe history

### `Chummer.Media.Contracts`

Owns:

* rendered packet and recap outputs

Must not own:

* dossier meaning itself

## Canonical rules

* A dossier is not only a PDF, card, or export.
* A build is not the same thing as a living dossier.
* A recap artifact is downstream of dossier and campaign truth, not a replacement for it.
* An origin dossier is optional narrative context and may seed later coaching, but it must not overwrite deterministic build truth.
* Replay-safe recovery must link back to the same dossier story instead of inventing a separate continuity object.
* Publication-safe projections may simplify or redact, but they must not fork semantic identity.

## Origin dossier bundle

The current desktop dossier lane may generate an optional `Origin Dossier Bundle` for either:

* a new character before the build is finalized, or
* an existing finished character when the player wants narrative packaging without reopening mechanics

The bundle can include:

* approved origin canon
* dossier PDF
* portrait candidate set and one selected portrait
* scene candidate set and one selected scene
* a selectable narration posture with a default narration packet and an alternate narration packet
* video storyboard and vidBoard packet
* local media-factory render requests and receipts

The origin bundle is downstream of the runner dossier.
It can inform ALICE suggestions, but it must not become the source of legality, nuyen, ware entitlement, or quality truth.
GM allowances and requirements may seed the origin bundle, including extra gear, ware, availability exceptions, required magical activity, required addiction hooks, minimum attribute posture, or table-specific starting resources.
Those inputs are table context until the player or GM commits matching mechanical edits through the normal character workflow.

## User-safe promise

The user should be able to say:

> this is still my runner, my crew, and my run, even after I switched surfaces, disconnected, came back, or generated a recap packet.

## Claimed-device restore rule

A second claimed device should restore the dossier story through typed refs rather than raw file mirroring.

That restore may surface:

* recent runner identity
* last-known campaign binding
* newer-draft cues from another device
* explicit latest, compare, branch, or stay-local choices

It must not silently replace a local draft, hide a rule-environment mismatch, or pretend an artifact export is the canonical dossier.
