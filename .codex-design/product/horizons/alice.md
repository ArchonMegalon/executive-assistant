# ALICE

## Table pain

Players often discover bad builds, illegal interactions, or weak upgrade paths only after the run has already gone sideways.

## Bounded product move

Chummer would compare builds, catch trouble before play, and explain tradeoffs without making up rules or legality.
The first proof slice for that horizon is:

```text
BUILD GHOST 001
```

BUILD GHOST lets a player or GM branch the current runner into one or more temporary comparison ghosts, change gear, qualities, attributes, augmentations, or rule-environment assumptions inside those ghosts, and then inspect the delta before touching the canonical character.

The product move is not "AI build advice."

It is:

* side-by-side ghost variants of the same runner
* deterministic delta receipts
* campaign-fit and legality warnings
* explicit apply-or-discard posture
* no silent mutation of the live runner

The core user promise is:

> Let me see what happens before I commit the change.

## Table scene

A player is about to spend the last of their starting nuyen.

They duplicate the current runner into:

* `Ghost A` - wired reflexes and leaner armor
* `Ghost B` - better deck, weaker body

Chummer shows both ghosts beside the live runner, explains what changed, flags that Ghost B breaks the campaign starting-gear posture, and shows that Ghost A survives better outside the host.

The player discards Ghost B, applies Ghost A, and keeps a receipt of what changed.

## What it must never do

BUILD GHOST must never:

* mutate the canonical runner before an explicit apply action
* invent mechanics, legality, or campaign allowances
* hide what changed between the source runner and a ghost
* turn external assistants into a second rules engine
* become a public-social or testimonial lane

## Trust boundary

The source of truth remains the engine-owned runner state and the active rule environment.

Ghosts are derived working copies.
They may produce receipts, deltas, warnings, and compare briefs, but they do not become canonical until a human explicitly applies a change set.

External tools may help draft copy for compare briefs or summarize an already-computed delta.
They do not compute build truth.
Facepop is not part of the runtime feature path; it remains a public concierge/testimonial tool and does not belong in BUILD GHOST.

## Likely owners

* `chummer6-core`
* `chummer6-ui`
* `chummer6-hub`

## Tool posture

Research and assistive drafting tools may support operator-facing explanations, but analysis outcomes stay grounded in engine-owned semantics.

## Foundations

* explain views that show their work
* deterministic runtime data
* strong comparison flows
* snapshot / branch / apply receipts for runner state
* rule-environment overlays that can be compared without mutating the active build

## Build path

* intent: eventual product lane
* current state: horizon
* next state: bounded research

## First proof slice

### BUILD GHOST 001

The first bounded slice should prove:

* clone the current runner into `Ghost A` and `Ghost B`
* let the user change a constrained set of build inputs inside each ghost
* show nuyen, legality, role-fit, and weak-link deltas
* compare the ghosts against the source runner in one surface
* discard a ghost cleanly
* apply one reviewed ghost delta back onto the canonical runner with an approval receipt

The first slice is successful when a user can answer:

* Which variant is legal here?
* Which variant is stronger for this campaign?
* What did I lose by taking the upgrade?
* Can I undo this safely before I commit?

## Owner handoff gate

Build-ghost comparison and apply flows must consume core-owned truth and explicit apply receipts rather than assistant-side heuristics or silent runner mutation.

## Why still a horizon

Chummer still needs sturdier compare-and-explain views before it should start giving confident build advice.
It also needs branch-and-apply semantics that feel safe enough for players to trust with a real runner instead of a disposable test file.
