# Product Boundary

## Core paying-customer product

Executive Assistant is currently scoped to:

- one executive
- one operator
- Gmail + Calendar first
- one morning memo
- one decision queue
- one commitment system
- approvals and auditability

## In scope browser surfaces

- `/`
- `/product`
- `/integrations`
- `/security`
- `/pricing`
- `/docs`
- `/get-started`
- `/sign-in`
- `/app/*`
- `/admin/*`

## Out of scope by default

The following are not part of the core product boundary and must stay disabled in product deployments unless explicitly enabled for a separate use case:

- `/memorials/*`
- `/memorials/files/*`
- `/memorials/*/voice-*`
- `/memorials/*/realtime`
- `/results/*`
- `/tours/*`
- property/provider public surfaces
- provider proof scripts and LTD receipt scripts
- Chummer/Fleet/Black Ledger mirror receipts and release-control projections

## Project modes

The repo carries multiple planes, but they are not one product claim:

- `EA_CORE`: shipping executive office product. Morning memo, decision queue, commitments, approvals, auditability.
- `MEMORIAL`: separate Manfred memorial runtime. Public pages, realtime voice, voice profile, A/B testing, and memorial assets.
- `PROVIDER_LAB`: operator-only proof lanes for JoggAI, MagicFit, Poppy, Unmixr, FlipLink, and similar providers.
- `CHUMMER_RELEASE_CONTROL`: external Chummer/Fleet/Black Ledger receipt projection and gold-map evidence.
- `PROPERTY`: separate PropertyQuarry/provider-search product plane.

Executable mode truth is materialized in `.codex-design/product/PROJECT_MODES.generated.json`.
Presentation scope for a normal EA core demo is materialized in `.codex-design/product/SHOW_SURFACE_MANIFEST.generated.json`.

## Runtime flags

- `EA_ENABLE_PUBLIC_RESULTS=0`
- `EA_ENABLE_PUBLIC_TOURS=0`
- `EA_ENABLE_PUBLIC_MEMORIALS=0` for EA core deployments unless the selected mode is `MEMORIAL`

Legacy compatibility flag:

- `EA_ENABLE_PUBLIC_SIDE_SURFACES=1` enables both surfaces together, but product deployments should prefer the explicit per-surface flags.
