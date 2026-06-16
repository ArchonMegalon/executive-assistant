# Telegram Flagship Runtime Design

## Purpose

This document defines the bounded Telegram runtime posture for Executive Assistant and adjacent Chummer/Fleet projections.

Telegram is an adapter and companion surface.
It is not:

* the account core
* the release authority
* the canonical support inbox
* a second product truth plane

## Product posture

Telegram may serve three bounded roles:

1. linked identity return path
2. lightweight assistant companion surface
3. controlled outbound/inbound delivery adapter for approved workflows

The flagship runtime must preserve the same office-loop and truth-plane rules that apply on web surfaces:

* account truth remains outside Telegram
* queue, milestone, blocker, and contract truth remain outside Telegram
* assistant runtime may summarize and route, but must not invent canon
* approvals and evidence remain visible in the primary system of record

## Allowed flagship behaviors

* receive bounded identity-linked messages
* show short assistant replies and task/status confirmations
* route users back to the canonical web surface when deeper review is required
* deliver approved notifications and follow-up prompts
* keep channel-specific metadata lighter when policy requires it

## Forbidden flagship behaviors

* arbitrary user-provided Telegram bots as first-wave default entry
* Telegram as the sole approval surface for important irreversible actions
* Telegram as the only place where evidence or review context exists
* Telegram-specific product semantics that diverge from mirrored canon
* hidden support, entitlement, release, or roadmap truth in Telegram state

## Runtime rules

* Telegram ingress must authenticate through the governed bot and secret path.
* Telegram bindings must resolve to the same principal/account model as the primary product.
* Async replies, retries, and recovery must remain observable in the runtime ledger.
* Telegram fallback behavior must degrade toward safe acknowledgement and web handoff, not fabricated certainty.

## Flagship release expectations

Telegram can participate in flagship-grade runtime claims only when:

* the adapter routes are documented and smoke-covered
* channel-bound secrets and bot configuration are governed
* approval/evidence boundaries remain intact
* release assets and operator docs describe Telegram as a bounded companion surface rather than a product truth plane

## Canon links

Primary supporting canon:

* `IDENTITY_AND_CHANNEL_LINKING_MODEL.md`
* `PUBLIC_USER_MODEL.md`
* `PUBLIC_AUTH_FLOW.md`
* `PUBLIC_RELEASE_EXPERIENCE.yaml`
* `PROVIDER_AND_ROUTE_STEWARDSHIP.md`
