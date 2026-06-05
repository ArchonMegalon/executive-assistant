# KNOWLEDGE FABRIC

## The problem

Rules answers are expensive, repetitive, and still too easy to hallucinate when every help or assistant lane has to reconstruct understanding from raw materials on demand.

## What it does now

Chummer builds knowledge projections from core-owned source packs and engine truth.
Those projections may include chunks, embeddings, graph edges, searchable receipts, citations, and explain helpers, but they remain derived artifacts rather than a second source of truth.

## Likely owners

* `chummer6-core`
* `chummer6-hub`
* `chummer6-ui`

## Key tool posture

* `Prompting Systems` - explain and prompt-shaping support
* `Documentation.AI` - downstream docs/help projection
* `AI Magicx` - bounded synthesis support
* `1min.AI` - bounded specialist explain/generation support
* `BrowserAct` - bounded capture and operator fallback
* `Paperguide` - cited research helper

## What has to be true first

* core-owned source packs and receipts
* explain provenance canon
* explicit "AI never computes mechanics" rule
* derived-projection storage and publication rules

## Current shipped posture

This lane is shipped as a derived, cited, non-authoritative knowledge projection layer.
Help and assistant flows are required to stay grounded in core-owned truth rather than treating the projection store as a second rules source.

## Current boundary

Knowledge Fabric remains safe only while the projections stay visibly derived, cited, and non-authoritative.
Future assistant depth can expand, but it does not change the rule that engine truth and source-pack truth stay upstream of every projection.
