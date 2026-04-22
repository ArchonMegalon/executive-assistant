# Build Lab product model

## Purpose

Build Lab is the flagship Build plus Explain surface for Chummer.
It turns deterministic rules truth into comparable build ideas, tradeoff projections, and handoff-ready dossier or campaign candidates.

## Product promise

* intake starts from a runner idea, current dossier, or campaign need
* variant generation, scoring, and projection stay grounded in engine-owned truth
* compare, timeline, trap-choice, role-overlap, and active-effect views stay explainable rather than magical
* chosen variants can hand off into the living dossier, campaign continuity, or publication lanes without re-entering data by hand
* conditional mechanics such as drugs, foci, sustained effects, acquisition timing, and reputation spends stay visible as first-class state rather than hidden side effects
* the active ruleset, preset, and amend package set stay visible and diffable so build output never feels detached from the rule environment that produced it
* SR4, SR5, and SR6 flows feel authored where their build logic or table expectations materially diverge, instead of being flattened into one generic lowest-common-denominator compare view

## Core product objects

* build idea
* candidate variant
* progression timeline
* explain packet
* export or handoff target
* conditional-effect state rail
* rule-environment receipt

## Ownership split

* `chummer6-core` owns deterministic variant generation, scoring, projection hooks, and explain-ready DTOs
* `chummer6-ui` owns intake, compare, timeline, export, and operator-facing Build Lab UX
* `chummer6-hub` may store handoff targets, dossier links, and campaign-aware follow-through, but it does not invent rules math
* `chummer6-design` owns the product promise, vocabulary, and boundary discipline

## Integration rules

* Build Lab consumes `Chummer.Engine.Contracts`; it does not become a second rules engine.
* Build Lab outputs may seed a living dossier or campaign plan, but dossier identity and campaign continuity remain in `Chummer.Campaign.Contracts`.
* Explain hooks must remain visible enough that "why this variant" can be audited without private operator folklore.
* Build Lab must expose source-linked hints, grouped organizational state, and receipt-backed conditional toggles instead of hiding these behind freeform notes or silent modifiers.
* Build Lab must compute against an explicit compiled rule environment, not against implicit local custom-data state.
* Preview and compare views must be able to show what changed because of source packs, presets, or amend packages before the user commits a variant or handoff.
* Export or handoff actions are explicit relationship or publication seams, not hidden side effects.

## Flagship-grade bar

Build Lab is not flagship grade until:

* dense compare and inspection flows stay comfortable at expert speed
* timeline, active-effect, and conditional-state surfaces feel intentionally designed rather than debug panels
* ruleset-specific differences are surfaced with authored terminology and UI where needed
* the active rule environment is visible enough that a user can tell whether a package choice changed the outcome
* a player can understand "why this variant" without leaving the product or trusting invisible operator knowledge

## Non-goals

* a chat-only replacement for structured compare and projection flows
* UI-local scoring or legality math
* a second campaign truth store
* a generic simulation sandbox with no dossier, campaign, or publication handoff

## Legacy issue pressure absorbed here

Build Lab is the canon home for several long-running legacy pain points that still fit the flagship product:

* grouped qualities and grouped active-effect organization
* source-linked acquisition or rules hints instead of mystery labels
* toggleable conditional modifiers with visible explain receipts
* calendar-aware training, acquisition, and downtime planning
* transaction-safe bundle or PACK previews instead of partial hidden edits
* rule-environment and amend-package activation with preview, dependency truth, and proof of activation
