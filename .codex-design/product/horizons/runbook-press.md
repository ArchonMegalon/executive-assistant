# RUNBOOK PRESS

## The problem

GMs, creators, and operators need consistent runbooks, tutorials, primers, and manuals without turning prose tooling into a second source of truth.

## What it does now

Runbook Press is the Chummer-owned packet and approval lane for:

* install and update explainers
* restore and recovery runbooks
* rules and UI walkthroughs
* operator and GM procedures
* primers, handbooks, and campaign-facing manuals

The authoring split is explicit:

```text
Custom Chummer code:
  source of truth, packet builder, rule and legal validation, lineage, receipts, export, approval gates

Subscribr:
  outlines, scripts, runbook narration, tutorial drafts, hooks, titles, shot lists, production planning

First Book ai:
  premium long-form book and manual treatment after a packet is already approved
```

Runbook Press complements JACKPOINT instead of duplicating it.
JACKPOINT owns the artifact-heavy dossier and briefing lane.
Runbook Press owns the source-bound procedural and long-form explainer lane.

## Likely owners

* `chummer6-core`
* `chummer6-hub`
* `chummer6-hub-registry`
* `chummer6-media-factory`

## Key tool posture

* `Subscribr.ai` - default creative and production layer for runbook scripts, tutorial drafts, titles, hooks, and shot lists from approved packets
* `First Book ai` - premium book and manual lane after packet approval
* `MarkupGo` - document rendering and packet export sibling
* `Documentation.AI` - downstream help/docs projection
* `vidBoard` - campaign primer and module explainer video lane
* `Soundmadeseen` - optional narrated companion assets
* `Paperguide` - bounded cited research support
* `Unmixr AI` - bounded candidate voice lane until proven

## What has to be true first

* approved `chummer.content_source_packet.v1` packets
* source hashes, allowed claims, forbidden claims, and expiry
* release receipts, UI receipts, and route evidence when the topic depends on them
* packet-to-script validation and export hashing
* human review and publication approval flows
* direct-publish disabled proof for every provider lane

## Current shipped posture

Runbook Press remains a shipped first-party Chummer lane, but the authoring split is now formalized:

* Chummer builds and validates truth.
* Subscribr explains that truth in script and production-ready form.
* First Book ai only receives already-approved packet sets when the target is a polished long-form manual or book.

The public route and proof lane stay first-party.
Provider workspaces are downstream draft systems, not publication authority.

## Source packet rule

Every runbook handoff starts with a Chummer-owned content packet.

Required fields include:

* `runbook_id`
* `mode`
* `target_provider`
* `target_output`
* `source_heads`
* `sources`
* `allowed_claims`
* `forbidden_claims`
* `approval`
* `expires_at`

Typical modes:

* `RUNBOOK_STRICT` for deterministic procedural content
* `RUNBOOK_VIDEO` for approved tutorial and explainer versions
* `PREMIUM_BOOK_MANUAL` for First Book ai handoff after approval

Provider exports that drift from the packet are rejected.

## Current boundary

Runbook Press only works if the draft, export, validation trail, and publication record stay aligned from first packet to final artifact.

The governing rule is simple:

```text
Chummer code answers:
  What is true?
  What is allowed?
  What source proves it?
  What was approved and published?

Subscribr and First Book ai answer:
  How do we explain it well?
  How should it be structured for a viewer or reader?
```

No provider may widen release claims, rules claims, or publication rights beyond the approved Chummer packet and receipt trail.

The shared gold-production promotion gate for this lane and `Origin Dossier` lives in `products/chummer/RUNBOOK_AND_ORIGIN_PROVIDER_GOLD_PRODUCTION_GATE.md`.
