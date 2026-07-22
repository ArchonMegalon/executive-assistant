# Governed Spatial Render Revision 10 Route Implementation Handoff

Date: 2026-07-11 (Europe/Vienna)

State: `bounded_backend_implementation_authorized`

Milestone: `2A_continuous_route_revisit`

Maximum claim: `route_contract_and_product_planner_locally_verified`

Provider execution, quota mutation, live data, browser, render, UI, deployment,
publication, promotion, canary, and readiness: `blocked`

## Accepted authority

The worker must verify these exact files before editing:

| Exact path | SHA-256 | Mode |
| --- | --- | ---: |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_REVISION_10_CONTINUOUS_ROUTE_REVISIT_AMENDMENT.md` | `c5dd35d971c7986169223020ad7c51a4cfdc1c1aa4aa9f8c96d801d05713337f` | `0664` |
| `/docker/property/PROPERTYQUARRY_CONTINUOUS_ROUTE_REVISIT_AUTHORITY_ADDENDUM.md` | `e4edc82ff37f2a3f2937e62cd02ae8ea1e22aff6bfb292103c8ec1d0cb7bc9d5` | `0600` |
| `/tmp/GOVERNED_SPATIAL_RENDER_REVISION_10_CONTINUOUS_ROUTE_REVISIT_REVIEW.final.md` | `3d5f8f4f2f008a06a070b1eec65f0cb074f90c78e4bc2ae3198468f049ba1273` | `0600` |
| `/tmp/GOVERNED_SPATIAL_RENDER_MILESTONE_1B_CONTROLLER_ACCEPTANCE.final.md` | `e18cb67977f0dcc3eea22a2b84f38182ae78da95e4fdaefa757d65bee284ebd2` | `0600` |

Controller dispatch provenance for the independent review:

- agent id: `019f521e-ceae-7f81-a887-40001f4975b0`;
- requested model: `gpt-5.6-sol`;
- reviewer findings: P0 `0`, P1 `0`, P2 `0`;
- reviewer writes/network/provider/quota/browser/runtime actions: `0`;
- decision: `ACCEPT` on the exact candidate hashes above.

All eight immutable R9 bindings remain required and read-only:

| Exact path | SHA-256 | Mode |
| --- | --- | ---: |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_REVISION_9_INDEPENDENT_REREVIEW_HANDOFF.md` | `431881fd03814b91dafa009c63abf4791264413ff7476015fec187039dd4e10a` | `0664` |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_REVISION_9_FROZEN_MATRIX.py` | `325897ba027c8f8b5041e15e2b21fabc3d4ca4b3c982b79ef92edb0096f1210f` | `0664` |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_REVISION_9_CASE_MANIFEST.json` | `b9f17c0ea2681cd698b8df4f5ed3bb2a66d3cb94d31376972d136834c6a6a6ad` | `0664` |
| `/tmp/GOVERNED_SPATIAL_RENDER_REVISION_9_INDEPENDENT_REREVIEW.final.md` | `389d312ad4e037e9e2b99d11e71b242b03119afec5fe6c65adf377a25d1557d2` | `0600` |
| `/docker/chummercomplete/chummer-design/products/chummer/GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml` | `f86e6f737ba3333f7e84d8196481cda4c4cc34dc08d6b5aff5a7465af303546f` | `0664` |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_PACKET.md` | `874f3ce32c160d396814381cee98ad936cb53bbb15f95a5591fecf9af17f82e7` | `0664` |
| `/docker/property/PROPERTYQUARRY_GOVERNED_SPATIAL_RENDER_AUTHORITY_DECISION.md` | `401fe42211e2d8283ea9ca2a7cfc1a1eaffc80ff13c63fdf9e6158a116eff50a` | `0600` |
| `/docker/EA/PROPERTYQUARRY_CHUMMER_GOVERNED_SPATIAL_RENDER_HANDOFF.md` | `e6ceebaedf91ef50a9e6179ac8775bbdb684147ffe1ca3ccc72175abcf68ee06` | `0600` |

A mismatch stops implementation.

## Existing implementation baselines

| Path | SHA-256 |
| --- | --- |
| `/docker/EA/ea/app/services/governed_spatial_contract.py` | `af5cef6634c787995e9807f89887f99b4944886c27e86d0e38e0c31f7c4b861f` |
| `/docker/EA/ea/app/services/governed_spatial_render.py` | `90cf2d1c8b8ba997082893904b640e272878c004a8aaa79c16c5eae29465d363` |
| `/docker/EA/ea/tests/test_governed_spatial_render.py` | `7d20979a73e81674a057f6b170a070bc99d79c7c7942ec47f755d8295c5d1280` |
| `/docker/EA/ea/tests/test_governed_spatial_render_contract.py` | `a786f33b38ede5e79fc17aa5bc35d4607a6112b0e9df72ed5c0edf7f23d99f4b` |
| `/docker/property/ea/app/product/property_tour_hosting.py` | `a8fc411e1e522c799b0b99c270beff80a07ab3d2cbe79c3947f064c3967e401d` |
| `/docker/property/tests/test_governed_spatial_render_bridge.py` | `ca111ee41be00b5aa2cb90f6ce76715ddffd90aad5eb7a4ad5a62a2b577477c8` |

The trees are intentionally dirty. Preserve every concurrent or pre-existing
change. Do not reset, checkout, stash, clean, stage, commit, or rewrite an
unowned path.

## Exact worker-owned files

The worker may edit only:

- `/docker/EA/ea/app/services/governed_spatial_contract.py`
- `/docker/EA/ea/app/services/governed_spatial_render.py`
- `/docker/EA/ea/tests/test_governed_spatial_render_contract.py`
- `/docker/EA/ea/tests/test_governed_spatial_render.py`
- `/docker/property/ea/app/product/property_tour_hosting.py`
- `/docker/property/tests/test_governed_spatial_render_bridge.py`

No API, app factory, privacy lifecycle, public serving, design, schema,
registry, requirements, environment, compose, provider, Chummer product, UI,
asset, generated, or deployment file is owned.

## Shared contract implementation

Implement the accepted route semantics exactly:

1. Keep `required_room_ids` nonempty and unique.
2. Treat `route_room_ids` as an ordered visit sequence.
3. Require route values to be valid required-room tokens.
4. Require route set equality with required-room set.
5. Reject consecutive duplicate rooms.
6. Enforce `len(route) <= 2 * len(required) - 1`.
7. Enforce `allow_revisit == (len(route) != len(set(route)))` exactly.
8. Validate each transition against declared portals as an undirected edge.
9. Reject self portal edges and duplicate undirected request portal edges.
10. Preserve normalized hashing of the exact sequence and revisit flag.

For `GovernedSpatialSourcePacketV1`:

- allow repeated route visits under the same `2N-1` and no-consecutive-repeat
  bounds;
- require route set equality with all source rooms classified walkable;
- reject route rooms outside inventory or classified non-walkable;
- reject self source portals and duplicate portal identities;
- treat a walkable source portal as bidirectional because no one-way field
  exists; and
- preserve inaccessible and route-exclusion fail-closed behavior.

## Orchestrator implementation

Update cross-source validation to:

- require exact request/source route-sequence equality, not set equality;
- derive revisit truth and reject a request flag mismatch;
- validate request portal inventory and every route transition against the
  undirected source portal set;
- keep required-room equality with the complete walkable set;
- keep route exclusions forbidden;
- expose only bounded `route_visit_count` and `route_revisit_count` quality or
  telemetry metrics if metrics are added; never room identifiers; and
- preserve zero provider/quota actions in compose.

Do not weaken signing, idempotency, execution-target, evidence-freshness,
privacy, publication, or build-state behavior.

## PropertyQuarry implementation

Keep product contract name
`propertyquarry.governed_spatial_tour_input.v1` and implement exact
version-specific allowlists.

### Version 1.0.0

- Preserve the current exact field allowlist.
- Require legacy `route_room_ids` as a unique explicit final route.
- Preserve current ordered transition validation and `allow_revisit=false`.
- Reject `route_priority_room_ids` and `route_start_room_id`.

### Version 1.1.0

- Use the `1.0.0` allowlist with `route_room_ids` removed.
- Require `route_priority_room_ids` and `route_start_room_id`.
- Require a unique priority whose set equals all walkable rooms.
- Require start room to equal the first priority item.
- Reject legacy `route_room_ids`.
- Build undirected adjacency from verified walkable source portals.
- Sort neighbors by priority rank, then stable room token.
- Use deterministic DFS, append parent on portal returns, and truncate after
  the first visit of the final previously unvisited room.
- Reject disconnected graphs, self portals, duplicate portal identities,
  unknown/non-walkable rooms, or an output beyond `2N-1`.
- Deduplicate adjacency for multiple differently identified doors joining the
  same two rooms.
- Emit the expanded sequence identically in generic request/source packets.
- Set `allow_revisit` from actual output.
- Bind product version, priority, start, expanded route, and revisit flag into
  deterministic bridge/idempotency material.

The planner must not use provider or brand branches and must not fabricate a
portal, room, cut, teleport, or exclusion.

## Required tests

Add focused positive and negative tests for every item in the accepted
Revision 10 matrix, including:

- legacy `1.0.0`, endpoint linear `1.1.0`, interior linear, one-room, hub,
  branch, cycle, and cross-edge layouts;
- room and portal input permutations with identical output;
- generic route exactly at `2N-1` accepted and `2N` rejected;
- duplicate route with false revisit, unique route with true revisit, and
  consecutive duplicate rejection;
- malformed/partial/duplicate/extra/non-walkable priority and start mismatch;
- self portal, duplicate portal identity, missing portal, disconnected graph;
- reverse source portal traversal;
- exact request/source reorder and substitution attacks;
- changed route idempotency conflict and restart replay;
- full room coverage and forbidden exclusions;
- no provider/combat fields and no private projection leakage; and
- compose action counters remain zero.

Preserve and rerun all existing suites.

## Acceptance commands

```text
cd /docker/EA/ea && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q tests/test_governed_spatial_render_contract.py tests/test_governed_spatial_render.py
cd /docker/EA && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ea pytest -q tests/test_governed_spatial_render.py tests/test_governed_spatial_render_api.py tests/test_governed_spatial_quality.py tests/test_app_factory_contracts.py
cd /docker/property && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=ea pytest -q tests/test_governed_spatial_render_bridge.py tests/test_property_public_tour_manifest_contract.py tests/test_property_tour_provider_ownership.py tests/test_property_content_privacy.py tests/test_app_factory_contracts.py
```

Run `python3 -m py_compile` with an external `PYTHONPYCACHEPREFIX` over every
edited Python file and exact owned-path `git diff --check` in both repos.

## Required worker receipt

Write mode `0600`:

`/tmp/GOVERNED_SPATIAL_RENDER_MILESTONE_2A_ROUTE_WORKER.final.md`

It must include:

- status and maximum claim;
- exact changed paths and final SHA-256 values;
- pre-existing dirty status;
- test commands, counts, durations, and exit codes;
- intermediate failures and fixes;
- Revision 10 and R9 hash/mode recheck;
- genericity and observability hardening findings;
- explicit network/provider/quota/browser/runtime/deploy/publication zeros;
- residual risks; and
- `controller_review_required=true`.

## Stop conditions

Stop and report without widening scope on any authority hash drift, required
unowned edit, live/provider/quota action, production key or property data,
unresolved P0/P1, or inability to preserve existing dirty work.

Passing this milestone proves only local route contract and planner behavior.
It does not prove a rendered path, frame rate, rotation quality, provider
capability, mobile UX, video delivery, canary, or flagship readiness.
