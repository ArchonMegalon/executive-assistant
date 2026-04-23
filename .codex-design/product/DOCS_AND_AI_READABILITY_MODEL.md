# Docs and AI Readability Model

This EA-local product note defines how Chummer may use Documentation.AI-style tooling while keeping canon, docs, and AI-readable public surfaces separate.

## Boundary

Documentation.AI can help check public documentation readability, answerability, and AI-agent indexing posture.
Docs reflect canon.
Docs do not replace canon.

Canonical product decisions still live in approved design, repo, release, and review files.
Generated docs, public answers, and `llms.txt` material are publication surfaces that must cite their sources instead of becoming sources.

## Operating Rules

* Public docs must name or link the source canon they summarize.
* AI-readable exports must keep user-facing claims aligned with release gates and public feature registry truth.
* Readability suggestions can improve copy, structure, and indexing hints, but cannot change product scope, ownership, release status, or support commitments.
* Any cited answer flow must preserve enough source context for review.

## Freshness Gate

`DOCS_AND_AI_READABILITY_FRESHNESS_GATE.yaml` defines the non-blocking freshness check for this lane.
