# Build Lab product model

## Purpose

Build Lab is the flagship Build plus Explain surface for Chummer.
It turns deterministic rules truth into comparable build ideas, tradeoff projections, and handoff-ready dossier or campaign candidates.

## Product promise

* intake starts from a runner idea, current dossier, or campaign need
* variant generation, scoring, and projection stay grounded in engine-owned truth
* compare, timeline, trap-choice, and role-overlap views stay explainable rather than magical
* chosen variants can hand off into the living dossier, campaign continuity, or publication lanes without re-entering data by hand

## Core product objects

* build idea
* candidate variant
* progression timeline
* explain packet
* export or handoff target

## Ownership split

* `chummer6-core` owns deterministic variant generation, scoring, projection hooks, and explain-ready DTOs
* `chummer6-ui` owns intake, compare, timeline, export, and operator-facing Build Lab UX
* `chummer6-hub` may store handoff targets, dossier links, and campaign-aware follow-through, but it does not invent rules math
* `chummer6-design` owns the product promise, vocabulary, and boundary discipline

## Integration rules

* Build Lab consumes `Chummer.Engine.Contracts`; it does not become a second rules engine.
* Build Lab outputs may seed a living dossier or campaign plan, but dossier identity and campaign continuity remain in `Chummer.Campaign.Contracts`.
* Explain hooks must remain visible enough that "why this variant" can be audited without private operator folklore.
* Export or handoff actions are explicit relationship or publication seams, not hidden side effects.

## Non-goals

* a chat-only replacement for structured compare and projection flows
* UI-local scoring or legality math
* a second campaign truth store
* a generic simulation sandbox with no dossier, campaign, or publication handoff
