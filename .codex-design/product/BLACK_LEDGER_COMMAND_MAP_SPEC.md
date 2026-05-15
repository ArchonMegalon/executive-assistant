# Black Ledger Command Map Spec

## Purpose

The Black Ledger command map is the public-safe tactical world view for seeded and opt-in aggregate Black Ledger data. It answers:

- what changed in the last visible turn
- where pressure is rising
- which faction currently dominates a region
- which dispatch explains the visible movement

## Route family

- `/ledger`
- `/ledger/map`
- `/ledger/factions`
- `/ledger/factions/{factionId}`
- `/ledger/turns/{turn}`
- `/api/v1/ledger/worlds/{worldId}/map`
- `/api/v1/ledger/worlds/{worldId}/map/turns/{turn}`
- `/api/v1/ledger/worlds/{worldId}/map/tick-delta/{fromTurn}/{toTurn}`

## Runtime posture

Phase 1 is SVG-first and Chummer-owned:

- no provider-owned truth
- no external map branding
- no private campaign or support data
- list fallback always present

Later renderer upgrades may use MapLibre/deck.gl/PixiJS, but they must preserve the same contracts.

## MVP scope

- district polygons
- faction/event overlays
- arc overlays
- mode switcher
- replay lane
- sidepanel
- homepage teaser
- public-safe map API

## Verdict

The feature is complete only when the public route, API route, replay proof, accessibility fallback, and public-safety proof all agree.
