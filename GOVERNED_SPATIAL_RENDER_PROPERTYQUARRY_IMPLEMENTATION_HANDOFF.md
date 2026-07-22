# Governed Spatial Render PropertyQuarry Implementation Handoff

Date: 2026-07-11 (Europe/Vienna)

State: `milestone_1_implementation_authorized`

Design gate: `revision_9_independent_accept`

Maximum claim in this milestone: `backend_contract_implemented_and_locally_verified`

Readiness, launch, provider execution, publication, promotion, and deployment:
`blocked`

## 1. Purpose

Revision 9 independently accepted the canonical governed-spatial-render design.
This handoff opens one bounded implementation milestone for:

1. the generic shared EA governed spatial-render/tour backend; and
2. the PropertyQuarry backend bridge and its privacy lifecycle.

PropertyQuarry is the flagship product owner and first consumer. The shared
capability must remain provider-neutral and product-neutral so Chummer can use
the same implementation later for style packs, continuous runsite
walkthroughs, and approved fictional combat choreography without inheriting
PropertyQuarry assumptions.

This milestone does not authorize UI work, direct provider integration, live
provider calls, credit use, deployment, publication, promotion, or any
readiness claim.

## 2. Immutable design bindings

All implementation and review decisions in this milestone are downstream of
the exact artifacts below.

| Artifact | SHA-256 | Mode |
| --- | --- | ---: |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_REVISION_9_INDEPENDENT_REREVIEW_HANDOFF.md` | `431881fd03814b91dafa009c63abf4791264413ff7476015fec187039dd4e10a` | `0664` |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_REVISION_9_FROZEN_MATRIX.py` | `325897ba027c8f8b5041e15e2b21fabc3d4ca4b3c982b79ef92edb0096f1210f` | `0664` |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_REVISION_9_CASE_MANIFEST.json` | `b9f17c0ea2681cd698b8df4f5ed3bb2a66d3cb94d31376972d136834c6a6a6ad` | `0664` |
| `/tmp/GOVERNED_SPATIAL_RENDER_REVISION_9_INDEPENDENT_REREVIEW.final.md` | `389d312ad4e037e9e2b99d11e71b242b03119afec5fe6c65adf377a25d1557d2` | `0600` |
| `/docker/chummercomplete/chummer-design/products/chummer/GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml` | `f86e6f737ba3333f7e84d8196481cda4c4cc34dc08d6b5aff5a7465af303546f` | `0664` |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_PACKET.md` | `874f3ce32c160d396814381cee98ad936cb53bbb15f95a5591fecf9af17f82e7` | `0664` |
| `/docker/property/PROPERTYQUARRY_GOVERNED_SPATIAL_RENDER_AUTHORITY_DECISION.md` | `401fe42211e2d8283ea9ca2a7cfc1a1eaffc80ff13c63fdf9e6158a116eff50a` | `0600` |
| `/docker/EA/PROPERTYQUARRY_CHUMMER_GOVERNED_SPATIAL_RENDER_HANDOFF.md` | `e6ceebaedf91ef50a9e6179ac8775bbdb684147ffe1ca3ccc72175abcf68ee06` | `0600` |

The R9 independent receipt records:

- reviewer session `019f511e-37d6-74c2-8d48-7d877f5f42c3`;
- exact model `gpt-5.6-sol`;
- P0/P1/P2 findings: none;
- frozen matrix: `341/341` in one invocation;
- bound artifacts: `8/8`;
- protected repository parity: `4/4`;
- reviewer-attributable writes: zero; and
- decision: `ACCEPT` for canonical design only.

Any hash mismatch closes implementation fail-closed until reconciled by the
controller. Do not edit the bound design artifacts in this milestone.

## 3. Ownership contract

Ownership must remain exactly split as follows.

### Shared EA owners

Established EA/shared owners retain:

- the domain-neutral governed capability;
- provider-neutral request orchestration;
- duplicate-safe raw UTF-8 JSON ingress;
- bounded canonicalization and signed-envelope verification;
- the signing-key registry, global fingerprint uniqueness, and revocation;
- authorization, quota posture, idempotency, restartable request state, and
  immutable receipt lineage;
- structured telemetry; and
- internal compose-only and compose-and-build endpoints.

EA provides runtime machinery and derived telemetry. It does not become
canonical product, release, or public-route authority.

### PropertyQuarry owners

In `/docker/property`:

- `app.product.property_tour_hosting` owns the PropertyQuarry bridge;
- `app.api.routes.landing` owns privacy lifecycle intake and closeout;
- `public_tour_payloads` owns public payload enforcement;
- `property_tour_hosting` owns deletion and revocation execution; and
- PropertyQuarry product authority remains bound to
  `PROPERTYQUARRY_GOVERNED_SPATIAL_RENDER_AUTHORITY_DECISION.md`.

The bridge translates first-party PropertyQuarry truth into the shared
contract. It must not implement shared cryptography, provider orchestration, or
quota state locally.

### Existing Chummer owners

- `/docker/chummercomplete/chummer.run-services` remains the existing shared
  Chummer service consumer and pattern source.
- `/docker/chummercomplete/chummer-hub-registry` remains the existing registry
  owner.
- Reuse `HorizonGovernedRenderRequestComposerService` and
  `HorizonArtifactRequestService` patterns where present.

Milestone 1 may make narrowly necessary shared-contract changes in these
established owners only when the controller's inspected file list explicitly
assigns them to the worker. It must not build a Chummer product bridge, UI, or
public route in this milestone.

No product public surface may call a provider directly. No ownership may move
between EA, PropertyQuarry, run-services, hub-registry, media-factory, or
design.

## 4. Shared contract behavior

### 4.1 Raw ingress

The implementation must validate raw UTF-8 JSON before ordinary object
materialization and reject, at minimum:

- duplicate object member names at every depth;
- invalid UTF-8 and invalid Unicode scalar data, including unpaired
  surrogates;
- non-finite numbers;
- all floating-point values in the bounded signed domain;
- integers outside the accepted safe-integer range; and
- structurally invalid signed envelopes.

No parser behavior may silently collapse duplicate members before validation.

### 4.2 Bounded JCS domain

Canonicalization must implement the accepted bounded JCS contract:

- recursively admit only objects, arrays, strings, booleans, null, and safe
  integers;
- reject floats, non-finite values, unsafe integers, invalid Unicode, and
  unsupported runtime types;
- order object keys by UTF-16 code units;
- emit compact UTF-8 JSON compatible with ECMAScript `JSON.stringify` for the
  supported domain; and
- deep-copy the signed payload and delete exactly `signature_value` and
  `signed_payload_digest` before calculating the signed payload digest.

Cryptographic verification must use real Ed25519 and must not substitute a
digest comparison, test-only signature, or locale-aware/Python code-point key
ordering.

### 4.3 Key and signature lifecycle

The verifier and key registry must enforce:

- deterministic Ed25519 verification over the exact canonical bytes;
- canonical signature encoding, including terminal-bit constraints;
- key identifier and algorithm agreement;
- globally unique public-key fingerprints across the registry;
- fail-closed unknown, duplicate, malformed, inactive, expired, or revoked
  keys;
- signature/key validity windows and accepted freshness/chronology bounds;
- immutable registry evidence suitable for restart and audit; and
- revocation that invalidates later use without rewriting historical receipts.

Private signing material is not introduced, generated, logged, or persisted by
this milestone unless an already established test-only fixture owner requires
it. Production key custody remains outside this implementation milestone.

### 4.4 Authorization, quota, and idempotency

Compose-only is an audit path:

- it must never reserve, consume, compensate, or otherwise mutate provider
  quota;
- it must not call a provider;
- it returns a deterministic composition and audit receipt; and
- replay of the same normalized request is deterministic and restart-safe.

Compose-and-build is gated:

- it requires explicit `ConsumeQuota=true`;
- it requires valid authorization, current capability evidence, current quota
  evidence, kill-switch evidence, idempotency key digest, normalized request
  digest, and composition digest;
- it emits immutable reservation/attempt/mutation/consumption/compensation
  evidence according to the accepted state machine; and
- in Milestone 1 it must stop before any live provider invocation or actual
  credit mutation. Tests use deterministic fakes only.

The request store must persist and integrity-check compositions, builds,
indexes, and lineage on restart. Replay must return the original immutable
receipt; a conflicting request under the same idempotency key must fail closed
before quota or provider work.

Attempts are exact nonnegative integers and must not exceed the authorization's
maximum provider attempts. Booleans, fractions, negative values, NaN, and
Infinity are invalid numeric evidence.

### 4.5 State and lineage invariants

Implement the accepted schema and semantic checks together. At minimum:

- `authorization_verified` contains no reservation, attempt, mutation,
  consumption, or compensation lineage;
- `reservation_held` and `released` require reservation lineage, attempt zero,
  and null mutation/consumption/compensation lineage;
- committed/pending/cancelled-reconciliation attempt states require exact
  attempt and mutation lineage with null later receipts;
- consumed/closed-consumed/compensation-pending states preserve consumption
  lineage with null compensation until compensation exists;
- compensated and compensation-failed-blocked states preserve compensation
  evidence;
- `compensation_failed_blocked` keeps the immutable prior build lineage and
  has blocked posture;
- generic `blocked` cannot masquerade as a later execution state and carries
  null execution lineage; and
- build-allowed posture is impossible without all required non-null identity,
  authorization, capability, evidence-family, quota, and kill-switch proofs.

All failures are local contract failures. None project provider or product
readiness.

### 4.6 Domain-neutral spatial composition

Core fields describe source truth, styles, route policy, scenes/rooms, ordered
beats, continuity, outputs, and evidence without product or provider brands.

The same contract must support:

- PropertyQuarry decor/style packs and a continuous walkthrough that enters
  every source-classified walkable room; and
- later Chummer style packs, continuous runsite walkthroughs, and approved
  fictional combat choreography.

For `continuous_all_walkable_rooms`, required room identifiers must equal the
full source walkable-room set. Nonempty route exclusions block flagship
composition. A genuinely unavailable room must be source-classified as
non-walkable/inaccessible with provenance rather than excluded while still
called walkable.

Combat overlays are choreography only. Reject forbidden rules-result fields
recursively at any depth with useful field paths, including initiative,
damage, dice, and rules results. Explicitly allowlist choreography fields where
practical.

The shared core must not hardcode IKEA, Jungalow, Matterport, 3DVista,
MagicFit, OMagic, PropertyQuarry, Chummer, or any other product/provider brand.
Product adapters may carry product-owned style identifiers as opaque data.

## 5. PropertyQuarry bridge behavior

The bridge must:

- accept only first-party, product-owned property/source references;
- derive the complete source walkable-room set from PropertyQuarry truth;
- map decor/style and walkthrough intent into the domain-neutral shared
  request;
- attach PropertyQuarry-owned truth and privacy evidence refs;
- expose first-party provider-safe response JSON only;
- never expose provider URLs, raw provider identifiers, secrets, admin links,
  internal dispatch details, or unsupported readiness claims;
- use the shared compose-only path for preview/audit;
- require explicit quota intent for build requests while Milestone 1's provider
  executor remains disabled; and
- preserve immutable shared receipt references rather than reconstructing
  shared state locally.

`app.api.routes.landing` must provide bounded privacy intake and closeout
integration. `public_tour_payloads` must fail closed unless the relevant tour
artifact and privacy state are verified. `property_tour_hosting` must execute
retention expiry, deletion, and revocation idempotently and leave auditable,
provider-safe tombstone/closeout evidence.

The bound PropertyQuarry authority decision does not itself approve numeric
PropertyQuarry spatial-media retention values, and the Chummer privacy policy
explicitly cannot substitute for that product policy. Milestone 1 therefore
implements a typed, hash-bound numeric policy input and the complete lifecycle
mechanics, but production policy resolution defaults to `blocked` when that
input is absent, malformed, expired, or unapproved. Tests must use explicit
synthetic numeric policy fixtures and prove deadlines, expiry, deletion, and
closeout behavior. No worker may copy Chummer values into a PropertyQuarry
default, invent product policy, or make public serving/building eligible while
the independent PropertyQuarry numeric-policy gate remains absent.

## 6. Persistence, telemetry, and failure posture

Persistence must be private, restartable, integrity-checked, and atomic enough
that crashes cannot create duplicate provider/quota intent. Corrupt or
incomplete persisted state blocks replay and build progression.

Structured telemetry must distinguish at least:

- ingress accepted/rejected with safe reason codes;
- composition created/replayed/conflicted;
- authorization and evidence failures;
- quota posture transitions without exposing secret values;
- provider execution suppressed in this milestone;
- build state transitions and compensation posture;
- key verification/revocation outcomes;
- privacy intake, retention expiry, deletion, and revocation; and
- product adapter identity as a bounded dimension, not a core behavior branch.

Logs, telemetry, exceptions, public JSON, and receipts must not leak secrets,
private provider URLs, raw authorization material, private property data, or
signing material.

## 7. Milestone 1 test contract

Run focused tests first, then relevant broader slices. Tests must include
positive and adversarial cases for:

- duplicate-safe raw JSON, nested duplicate members, invalid Unicode, numeric
  limits, floats, non-finite values, and unsafe integers;
- bounded JCS ordering/escaping and supported-domain Node parity;
- real Ed25519 signatures, exact excluded-member deletion, malformed
  envelopes, mutations, key fingerprint uniqueness, chronology, expiry, and
  revocation;
- deterministic idempotency, restart/reload/replay, conflicting replay,
  bounded retry, and attempt ceilings;
- compose-only zero quota/provider actions;
- explicit build intent with fake quota/provider boundaries and immutable
  evidence;
- all authorization, generic-blocked, terminal, consumed, compensation, and
  compensation-failed lineage states;
- finite, plausible walkthrough/interactive quality measurements and exact
  nonnegative integer counts;
- full walkable-room coverage and fail-closed exclusions;
- recursive forbidden combat-rule fields and nested-beat regression;
- provider-safe public payloads and routes;
- privacy intake, numeric retention, expiry, deletion, revocation, and
  idempotent closeout;
- persistence integrity failures and fail-closed restart behavior; and
- cross-project genericity proving at least one PropertyQuarry-shaped and one
  Chummer-shaped request use the same core with no branded core branch.

No test may make a network request, call a provider/account API, mutate real
quota, use production signing material, deploy, publish, or modify live state.

The frozen R9 matrix is design evidence, not a substitute for implementation
tests. It may be read as the accepted contract and must not be edited or
reclassified by the implementation worker.

## 8. CodexEA worker contract

The outer controller must inspect only targeted existing implementation context
before launch and then name exact owned files. Launch exactly one bounded
CodexEA `worker` from `/docker/EA`; never use `ea-3`.

The contract environment must define:

- `CODEXEA_CONTRACT_OBJECTIVE`;
- `CODEXEA_CONTRACT_OWNED_FILES`;
- `CODEXEA_CONTRACT_READ_ONLY_CONTEXT`;
- `CODEXEA_CONTRACT_FORBIDDEN_FILES`;
- `CODEXEA_CONTRACT_ACCEPTANCE_TESTS`;
- `CODEXEA_CONTRACT_RUNTIME_ASSUMPTIONS_ALLOWED=false`;
- `CODEXEA_CONTRACT_STOP_CONDITIONS`;
- `CODEXEA_CONTRACT_MAX_RETRY_LOOPS`; and
- `CODEXEA_CONTRACT_REQUIRED_RECEIPTS`.

The worker must preserve all pre-existing dirty changes, keep an action log,
and stop immediately on scope ambiguity, design-hash drift, provider/quota/live
action, or a required change outside its exact owned files.

The same worker must complete two phases:

1. implementation plus focused and broader green tests; and
2. the required hardening pass for product/provider genericity,
   observability, restart safety, receipt completeness, and reusable structure.

Do not launch a helper, replacement, parallel worker, or second implementation
worker in this milestone.

## 9. Required worker receipt

The final worker receipt must state:

- status;
- worker/session identity and lane;
- files changed, with every path;
- exact focused and broader tests run;
- pass/fail/error/skip counts and exit codes;
- runtime actions taken;
- provider/account/quota actions, which must all be zero;
- assumptions made;
- genericity findings and hardening changes;
- observability and persistence notes;
- privacy/deletion/revocation evidence;
- action-log summary and any concurrent external drift;
- remaining risks and deferred work; and
- `controller_review_required: true`.

Weak, incomplete, or unsupported receipts are not accepted as Milestone 1
evidence.

## 10. Controller audit and stop gate

After worker exit, the outer controller must independently:

1. verify all immutable design bindings;
2. compare pre/post repository fingerprints and classify only worker-attributable
   writes, reporting concurrent drift honestly;
3. inspect every changed owned file and reject out-of-scope writes;
4. review shared-core genericity and product/provider leakage;
5. rerun focused tests and relevant broader slices without network/provider
   access;
6. verify compose-only and all controller/reviewer actions consumed zero quota;
7. verify the hardening pass and required receipt; and
8. write or report a Milestone 1 audit decision.

The controller then stops. It must not begin UI work, provider execution,
browser verification, deployment, publication, promotion, or launch/readiness
projection in this turn.

Passing Milestone 1 means only that the bounded backend implementation and
PropertyQuarry bridge are locally verified against the accepted canonical
contract. It is not a flagship, gold, launch, production, or readiness claim.

## 11. Controller-frozen Milestone 1 execution contract

Controller observation time: `2026-07-11` (Europe/Vienna).

The controller independently rehashed all eight immutable design bindings in
section 2 before opening this contract. Every digest and required mode matched.
The implementation must fail closed if any binding changes during the worker
run.

Pre-worker repository fingerprints (dirty trees are intentional and must be
preserved):

| Repository | HEAD | `git status --porcelain=v1 -z` SHA-256 |
| --- | --- | --- |
| `/docker/EA` | `e1b7c1604870e791fde2e978bd03323c19496578` | `85e12edf2b49894cd8df008788ed573e05a197d58ad7be25ca6d64e3c76bafea` |
| `/docker/property` | `9bb633a29699e49da2e5c842bb7762fc3aaf7b65` | `53be62ef673919883600bf8f2245b5758719f77f19152e03f0da68de79c6197e` |
| `/docker/chummercomplete/chummer.run-services` | `16ff4c810337fe4607d302fc8d95c09e54266bba` | `ad732604ac93afff0111aa41c1d467cd01d699619cbf63122f0f700c1f339d43` |
| `/docker/chummercomplete/chummer-hub-registry` | `da460b3d594a56c272f95d841244e6a457fe70b5` | `e65fa16829581f3b2f135000b24b840cdfa2377ede4b2adfd1097e2b275e3f28` |

Exact worker-owned files:

- `/docker/EA/ea/app/services/governed_spatial_render.py`
- `/docker/EA/ea/app/services/governed_spatial_contract.py` (new, only if the
  security/contract split materially improves reuse)
- `/docker/EA/ea/app/api/routes/governed_spatial_render.py` (new)
- `/docker/EA/ea/app/api/app.py`
- `/docker/EA/tests/test_governed_spatial_render.py`
- `/docker/EA/tests/test_governed_spatial_render_api.py` (new)
- `/docker/property/ea/app/product/property_tour_hosting.py`
- `/docker/property/ea/app/api/routes/public_tour_payloads.py`
- `/docker/property/ea/app/api/routes/landing.py`
- `/docker/property/tests/test_governed_spatial_render_bridge.py` (new)
- `/docker/property/tests/test_property_public_tour_manifest_contract.py`

The implementation may leave an owned file unchanged. It may not create any
other source, test, fixture, generated, receipt, cache, or harness file. The
worker final response is the receipt; no repository receipt file is owned.

Exact read-only pattern sources:

- `/docker/chummercomplete/chummer.run-services/Chummer.Run.Api/Services/Community/HorizonGovernedRenderRequestComposerService.cs`
- `/docker/chummercomplete/chummer.run-services/Chummer.Run.Api/Services/Community/HorizonArtifactRequestService.cs`
- `/docker/chummercomplete/chummer.run-services/Chummer.Run.Api/Services/PropertyquarryApartmentVideoArtifactRequestBridgeService.cs`
- `/docker/chummercomplete/chummer.run-services/Chummer.Run.Api/Controllers/InternalPropertyquarryApartmentVideoController.cs`
- `/docker/chummercomplete/chummer-hub-registry`

The existing EA implementation is a draft scaffold. In particular, HMAC
signatures and ordinary `json.dumps(sort_keys=True)` canonicalization are not
accepted substitutes for the R9 Ed25519 and bounded-JCS contract. Existing
tests that encode that draft behavior must be upgraded rather than used to
weaken the accepted design.

Focused acceptance commands:

```text
cd /docker/EA && PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_governed_spatial_render.py tests/test_governed_spatial_render_api.py
cd /docker/property && PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_governed_spatial_render_bridge.py tests/test_property_public_tour_manifest_contract.py
```

Relevant broader slices:

```text
cd /docker/EA && PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_governed_spatial_render.py tests/test_governed_spatial_render_api.py tests/test_governed_spatial_quality.py tests/test_app_factory_contracts.py
cd /docker/property && PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_governed_spatial_render_bridge.py tests/test_property_public_tour_manifest_contract.py tests/test_property_tour_provider_ownership.py tests/test_property_content_privacy.py tests/test_app_factory_contracts.py
```

All commands are local and offline. `ConsumeQuota=true` is exercised only
against deterministic fakes that record intent; actual provider and quota
actions remain zero. No server, container, browser, deploy, publication, or
runtime process may be started.

## 12. Controller recovery audit (2026-07-11)

Status: `provisional_local_green_not_milestone_accepted`

The sole CodexEA worker session was
`019f5169-0c0b-7402-a27c-d918ada2e9da`. Its vexp MCP failed to start and two
resume transports emitted out-of-contract function calls. One requested a
deployment; the wrapper did not execute it. The controller retired the worker,
launched no replacement, and verified zero worker-attributable writes and zero
runtime/provider/quota/deploy actions.

The outer controller then recovered bounded implementation work inside the
section 11 owned files. Concurrent EA sessions also wrote overlapping shared
contract bytes. Their changes were preserved and integrated rather than
reverted. EA therefore must not be claimed unchanged. During this interval its
HEAD moved independently from `e1b7c1604870e791fde2e978bd03323c19496578`
through multiple revisions to `cb7f63811f3d21a86f18aed0d9ab7c4efa9e5df6`.
Run-services and hub-registry retained exact HEAD and status fingerprints.

Current locally verified implementation includes:

- duplicate-safe raw UTF-8 ingress with finite transport numbers and safe
  integer bounds;
- bounded no-float JCS with UTF-16 key ordering;
- real Ed25519 composition signatures, canonical base64url enforcement,
  fingerprint uniqueness, chronology, expiry, revocation, and exact signed
  member exclusion tests;
- authorization/quota/idempotency semantic validation for every accepted
  lifecycle family, including generic blocked and
  `compensation_failed_blocked` immutable lineage;
- restart-checked composition/build receipt persistence and deterministic
  replay/conflict behavior;
- provider-neutral registry-driven artifact candidate resolution and a test
  proving an additional registry-authorized consumer without a product branch;
- internal compose/build routes with explicit quota intent and provider
  execution suppressed;
- structured provider-safe telemetry for composition/build create, replay,
  conflict, and blocked transitions;
- PropertyQuarry first-party bridge mapping full walkable-room truth into the
  shared contract;
- hash-bound numeric privacy policy intake with no invented default;
- private restartable lifecycle state, expiry blocking, idempotent deletion and
  revocation tombstones;
- operator-bounded privacy intake/status/closeout routes; and
- public-tour enforcement that fails closed for governed artifacts without
  accepted composition, verified artifact, active privacy, and unexpired
  retention.

Controller verification commands and results:

- EA focused plus broader slice: `104 passed`, exit `0`;
- PropertyQuarry focused plus broader slice: `21 passed`, exit `0`;
- targeted `git diff --check`: exit `0` in both repositories;
- all eight immutable design bindings: exact hash match;
- provider/account/quota actions from implementation and tests: `0`;
- server/container/browser/deploy/publication actions: `0`.

At the user's later explicit request, one factual ETA notification was sent by
the established PropertyQuarry operator Telegram transport at
`2026-07-11T14:06:08Z`. This was not a render-provider, quota, deployment, or
readiness action. The redacted mode-0600 receipt is
`/tmp/propertyquarry_flagship_eta_telegram_sent.json`, SHA-256
`6e52461c1af09adbcf9a998f018e3d1e055c2a6b70ec01a39da3546f28fe5001`.

Remaining Milestone 1 blockers:

1. no valid CodexEA worker receipt or worker hardening receipt exists;
2. the Ed25519 registry behavior is tested in memory but immutable registry
   persistence/loading is not yet wired into the runtime builder;
3. signed capability/authorization/quota evidence is semantically validated
   but the build endpoint still accepts opaque authorization references rather
   than requiring and verifying the complete signed envelope; and
4. controller review must be repeated after the overlapping EA writer is
   quiescent so final hashes can be attributed coherently.

Until all four close, the implementation remains local and provisional. UI,
live provider execution, quota consumption, deployment, publication,
promotion, and readiness claims remain blocked.

## 13. Technical closeout update (2026-07-11)

Status: `technical_scope_locally_green_process_receipt_missing`

After section 12, the controller closed technical blockers 2 and 3 without
expanding the owned-file boundary:

- `Ed25519KeyRegistry.from_path` now requires an exact file SHA-256, rejects
  links/missing files, verifies the registry's bounded-JCS digest, enforces
  canonical raw public-key encoding and fingerprint equality, and reconstructs
  validity/revocation state on restart;
- duplicate global fingerprints, file tampering, stale/future/expired receipt
  chronology, and persisted revocation all fail closed in regression tests;
- the runtime builder accepts registry and canonical-schema paths only with
  their exact expected SHA-256 values;
- the internal build route requires a complete evidence envelope;
- the service validates that envelope against the hash-bound canonical Draft
  2020-12 schema with format checking, then applies the cross-field semantic
  state validator and real Ed25519 verification;
- build ingress additionally requires `build_allowed`, active revocation
  posture, an allowed kill switch, exact composition binding, exact
  authorization reference, and exact attempt ceiling; and
- the signed evidence digest is included in immutable build request/audit
  lineage. Invalid or mutated evidence fails before receipt storage, quota, or
  provider action.

Final local verification after these changes:

- EA focused plus broader slice: `107 passed`, exit `0`;
- PropertyQuarry focused plus broader slice: `21 passed`, exit `0`;
- render-provider calls: `0`;
- provider jobs: `0`;
- quota reservations/consumption/compensation: `0`;
- deployment/publication/readiness actions: `0`.

The immutable Artifact Receipt verifier remains deliberately absent, so even a
valid signed `build_allowed` envelope projects `blocked` with
`trusted_immutable_artifact_verification_unavailable`. This is the required
Milestone-1 no-provider/no-readiness ceiling, not an implementation defect.
The PropertyQuarry production numeric retention policy also remains an
external product-authority gate; the implementation has no invented default
and tests use explicit synthetic policies only.

The overlapping EA files remained byte-stable during this closeout. The only
remaining Milestone-1 acceptance blocker is process evidence: session
`019f5169-0c0b-7402-a27c-d918ada2e9da` never produced the required valid worker
receipt. The controller does not fabricate or substitute that receipt. A
future controller decision must explicitly authorize either accepting the
controller-recovery audit as equivalent evidence or a new bounded worker audit;
until then formal Milestone-1 status remains unaccepted.
