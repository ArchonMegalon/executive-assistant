# Design petition: shared governed spatial-render contract

Petition ID: `ea-governed-spatial-render-contract-v1`

Prepared: 2026-07-11 (Europe/Vienna)

Status: `proposed_unsubmitted`

Authority: noncanonical EA-local petition artifact

## Decision requested

Approve, revise, or reject a cross-product contract named
`ea.governed_spatial_render_request.v1` for compose-only validation and later
governed execution of spatial media requested by PropertyQuarry and Chummer.

Also decide whether Chummer-owned fictional combat choreography may be carried
as an immutable scene overlay on a stable runsite route, and which canonical
repo owns that overlay contract.

## Why a decision is required

The current design mirror establishes EA as a provider-aware runtime substrate,
not a product or contract authority. It says missing cross-repo seams require a
petition rather than assistant-local canon.

The current Chummer horizon registry defines RUNSITE as an explorable pack with
route, tour, permissions, and provenance truth. Its public claim explicitly
stops short of live-map, combat, VTT, or tactical authority. PropertyQuarry is
an adjacent product and is not a Chummer horizon. The requested shared spatial
contract and combat-overlay semantics therefore cannot become durable product
truth through an EA-only change.

## Proposed ownership split

- Chummer Hub or another designated product plane owns approved runsite,
  encounter, actor, outcome, permissions, and user identity refs.
- PropertyQuarry owns property packets, room/portal graphs, style selection,
  product routes, and per-user onboarding-vignette state.
- Chummer media-factory or the designated canonical media contract repo owns
  durable artifact-family and overlay semantics.
- EA validates a versioned provider-neutral request, records private execution
  receipts, derives capability posture from current evidence, and later invokes
  provider adapters only after explicit authorization.
- Fleet and the product governor retain canary, rollback, provider-default, and
  promotion authority.
- Public/product projections expose first-party artifact state and safe reasons;
  provider names, URLs, task IDs, account IDs, balances, credentials, and traces
  remain private runtime evidence.

## Proposed contract invariants

- Artifact families are `rendered_diorama`, `interactive_tour`,
  `continuous_walkthrough`, and `onboarding_vignette`.
- Continuous paths require immutable room, walkable-mesh, and portal-graph refs;
  declared portals must connect every route transition and the route must cover
  every required room.
- Flagship walkthroughs allow no cuts or teleports.
- Style is a versioned product-owned pack; provider prompt compilation stays in
  private adapters.
- Product input rejects provider identifiers, provider URLs, raw provider
  account IDs, credentials, and secrets.
- Chummer combat overlays require immutable gameplay-truth and provided-outcome
  refs. EA does not calculate initiative, damage, actions, or outcome.
- Compose/audit never enqueues work and never consumes quota.
- A future build requires an accepted composition digest, a caller idempotency
  key, explicit `consume_quota: true`, a bounded provider-attempt count, an
  authorization ref, and an audit-event ref.
- A capability cannot project ready from design intent or environment variables;
  it needs a current evidence receipt and still cannot become artifact-ready
  until an authorized build and quality gates complete.

## Reversible local scaffold authorized by this petition

Pending canonical review, EA may keep an isolated, unregistered Python module
that validates and deterministically composes the proposed request, persists a
private create-once audit receipt, derives capability posture from supplied
receipts, and returns a provider-redacted product-safe projection.

This scaffold is not canon and must not:

- register a public, internal, or live route;
- enqueue a provider job;
- consume or reserve quota;
- choose or call a provider;
- change product routing or release posture;
- claim an artifact or provider is ready.

## Questions for canonical review

1. Which repo owns the durable cross-product spatial request and receipt schema?
2. Is PropertyQuarry a named external consumer, a Horizon capability, or a
   separately governed product bridge?
3. Does the existing RUNSITE boundary permit private pre-session fictional
   combat previews, or must combat remain a separate Chummer-only media recipe?
4. Which plane owns style-pack identity, licensing evidence, retention, and
   takedown policy?
5. Which capability receipts are authoritative for 3D-tour intake, continuous
   walkthroughs, and browser/continuity proof, and how long are they valid?
6. Which service owns idempotent build state, cancellation, retries, and quota
   compensation after a provider failure?

## Evidence and references

- `.codex-design/repo/IMPLEMENTATION_SCOPE.md`
- `.codex-design/review/REVIEW_CONTEXT.md`
- `.codex-design/product/HORIZON_REGISTRY.yaml`
- `.codex-design/product/ARTIFACT_FACTORY_PIPELINE_MODEL.md`
- `.codex-design/product/PROVIDER_AND_ROUTE_STEWARDSHIP.md`
- `PROPERTYQUARRY_CHUMMER_GOVERNED_SPATIAL_RENDER_HANDOFF.md`

## Acceptance and closeout

Canonical acceptance must name the contract owner, product bridges, overlay
boundary, quota authority, receipt authority, privacy/retention posture, and
promotion gates. Until then, the local scaffold remains compose-only and all
product-safe projections fail closed before `ready`.
