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

- `/results/*`
- `/tours/*`

## Runtime flags

- `EA_ENABLE_PUBLIC_RESULTS=0`
- `EA_ENABLE_PUBLIC_TOURS=0`

Legacy compatibility flag:

- `EA_ENABLE_PUBLIC_SIDE_SURFACES=1` enables both surfaces together, but product deployments should prefer the explicit per-surface flags.
