# World tick operator process

## Purpose

This file defines the governed operator loop for BLACK LEDGER world ticks.

The world tick is the main place where Chummer turns approved pressure, adopted intel, and completed runs into new job opportunities and published world consequences.

## Operating rule

World ticks are draftable and automatable, but they are not self-authorizing.

Each tick must move through:

1. input collection
2. draft synthesis
3. operator review
4. approval or rollback
5. publication and downstream projection

## Inputs

- faction `OperationIntent`
- resource allocation state
- research progress
- district pressure and heat
- adopted intel
- completed `ResolutionReport` objects
- scheduled runs
- unresolved clocks
- organizer season goals
- approved creator or published packets

## Outputs

- district pressure changes
- job seeds
- faction resource deltas
- unlocked special assets
- world map markers
- newsreel candidates
- campaign workspace cues

## Tick states

```yaml
world_tick:
  id: tick_seattle_0007
  world_ref: seattle_shared_01
  period: 2026-W19
  status: draft
  approval:
    required_by: world_operator
    state: pending
```

Recommended states:

- `draft`
- `pending_review`
- `pending_approval`
- `approved`
- `published`
- `rolled_back`

## Operator room

The operator room should provide:

- input summary
- faction moves
- heat changes
- job-seed candidates
- news candidates
- publication approvals
- rollback plan
- final publish action

`NextStep` is the preferred bounded operator process runner for this room.
It does not become canonical process truth.
Chummer-owned packets and mirrored registries remain authoritative.

## Approval rules

- The world operator or organizer must approve visibility grade before publication.
- GM-only or faction-secret consequences must not leak into public or player-safe outputs.
- A scheduled run does not produce a completed-run marker until a `ResolutionReport` is approved.
- Tick publication must retain the chain from source objects to outcomes.

## Rollback posture

Each tick must preserve:

- the draft packet
- the approval record
- the publication receipt
- the rollback or supersession path

If a visibility or authority error is discovered, Chummer must be able to retire or supersede the affected tick output without corrupting campaign truth.
