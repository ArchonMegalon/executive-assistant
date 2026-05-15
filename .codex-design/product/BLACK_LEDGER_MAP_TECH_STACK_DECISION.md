# Black Ledger Map Tech Stack Decision

## Current shipped decision

Phase 1 ships as:

- ASP.NET Razor view
- first-party SVG tactical renderer
- CSS animation for event pulse and arc motion
- light inline interaction script

## Why

- low dependency risk
- no provider branding
- works inside the current Hub runtime
- public-safe fallback is first-class instead of an afterthought

## Upgrade path

If the command map needs heavier rendering later, upgrade behind the same contracts:

- MapLibre GL JS
- deck.gl
- PixiJS
- GSAP

Those dependencies may render. They must not own truth.
