# World intel contribution and review policy

## Purpose

This file defines the practical contribution loop that lets players and GMs feed the city without turning raw submissions into canon.

## Canonical rule

World intel is participation fuel, not automatic truth.

Every contribution needs:

- scope
- spoiler class
- consent posture
- review state
- intended use
- contributor or pseudonymous provenance

## Contribution classes

- rumor
- field report
- district lore
- faction intel
- after-action consequence
- unresolved NPC hook
- region mood signal
- safehouse or black-market rumor
- creator seed

## Practical reward loop

The user should be able to receive a bounded, meaningful message like:

> Your Redmond rumor was reviewed, adopted into district pressure, and later generated a sabotage job.

That is the engagement loop.

## Review model

Detailed state definitions live in `INTEL_REPORT_REVIEW_STATES.yaml`.

Core states:

- pending review
- needs clarification
- reviewed
- adopted
- merged
- rejected
- false flag
- canonized

## Safety rules

- no automatic canonization
- no public release of private table lore without consent
- no spoiler leakage across visibility classes
- no copyrighted sourcebook text ingestion as “intel”

## First proof gate

**Seattle Open Run 001**

Includes:

1. one submitted rumor
2. one curator review
3. one adopted district-pressure effect
4. one player-safe notification back to the contributor

Success criterion:

> A user can see that their contribution mattered without ever confusing “submitted lore” with “official world truth.”
