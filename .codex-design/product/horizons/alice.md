# ALICE

## The problem

Players often discover bad builds, illegal interactions, or weak upgrade paths only after the run has already gone sideways.

## What it would do

Chummer would compare builds, catch trouble before play, and explain tradeoffs without making up rules or legality.

## What is live now

The first shipped ALICE slice is the Build Ghost compare bench:

* a public-safe ALICE route that explains the boundary and routes users into first-party compare work
* signed-in build handoffs that keep tradeoffs, progression outcomes, runtime compatibility, source hints, and apply/discard follow-through on one governed rail
* first-party compare artifacts such as compare briefs, what-if packets, and apply or discard receipts

This is not an assistant-side build oracle. The shipped lane is a Chummer-owned compare and handoff surface with bounded public framing.

## Likely owners

* `chummer6-core`
* `chummer6-ui`
* `chummer6-hub`

## Tool posture

Research and assistive drafting tools may support operator-facing explanations, but analysis outcomes stay grounded in engine-owned semantics.

## What has to be true first

* explain views that show their work
* deterministic runtime data
* strong comparison flows

## Current boundary

The live ALICE lane still does not mean Chummer can invent mechanics, override legality, or turn a public explainer into runtime truth.
The public entry, the signed-in compare bench, and the first-party receipts are live now; deeper simulation and coaching can widen later.
