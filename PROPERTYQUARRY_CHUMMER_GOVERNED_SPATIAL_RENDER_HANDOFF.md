# EA governed spatial-render handoff

Prepared: 2026-07-11 (Europe/Vienna)

Target owner: the Codex session working in `/docker/EA`

Source workspace: `/docker/property`

Status: implementation handoff, not a launch or readiness claim

## 1. Directive

Move the reusable 3D-tour and walkthrough-generation capability into EA's governed render lane. Product repos must request artifacts through a shared contract and must not own provider-specific orchestration.

Two consumers must use the same core:

1. PropertyQuarry: apartment dioramas, styled interactive 3D tours, and one continuous walkthrough that enters every walkable room.
2. Chummer: runsite tours in other visual styles and one continuous walkthrough that can include approved, non-graphic fictional combat choreography.

PropertyQuarry is the active product in the source workspace. Do not relabel this work as Chummer. Chummer is a second consumer of the generic EA capability.

The result must be a polished, minimal, reliable product that "just works." Gold is an intermediate evidence state, not the final objective.

## 2. Authority and boundaries

Follow `/docker/EA/AGENTS.md` and the mirrored design front door before editing. In particular:

- EA is the governed runtime and provider-execution substrate. It is not canonical Chummer product, user, entitlement, release, or queue truth.
- If the cross-product spatial-render contract is missing from mirrored canon, emit a design petition before inventing durable semantics locally.
- Reuse `HorizonGovernedRenderRequestComposerService` and `HorizonArtifactRequestService` where the Chummer bridge already exposes them.
- A product controller may translate product truth into the shared request. It must not call MagicFit, OMagic/MagicAI, 3DVista, Matterport, or another provider directly.
- Keep provider URLs, raw account IDs, credentials, and secrets out of product request payloads, truth refs, logs, screenshots, Telegram messages, and public receipts.
- A compose/audit call must never consume quota. Credit burn requires an explicit `consume_quota: true` build request.
- Provider availability is runtime truth backed by a current receipt. Environment variables or design intent alone never establish readiness.
- EA may store execution receipts and opaque product refs. It must not become the source of property records, Chummer encounter outcomes, user identity, or per-user UI state.

## 3. Required architecture

Build one provider-neutral spatial artifact pipeline with four artifact families:

- `rendered_diorama`: inspection-first, complete spatial overview.
- `interactive_tour`: navigable same-origin tour package, with 3DVista as the current PropertyQuarry primary lane.
- `continuous_walkthrough`: a single continuous camera path with no cuts or scene jumps.
- `onboarding_vignette`: an optional short generated moment, such as furniture assembly, delivered separately from the normal walkthrough.

Use this flow:

```text
Product-owned truth
  -> product bridge
  -> governed spatial render request
  -> compose-only validation
  -> EA artifact request
  -> provider capability selection
  -> restartable provider job(s)
  -> quality and provenance gates
  -> immutable artifact + private provider receipt
  -> product-safe ready/blocked projection
```

The provider-neutral contract is the stable interface. Provider adapters and provider selection are replaceable EA internals.

## 4. Capability index

Add EA to the active capability index as the orchestration lane for spatial artifacts. Use existing repository naming conventions, but preserve these semantic capabilities:

- governed spatial request composition
- rendered diorama generation
- 3DVista interactive tour intake and delivery
- MagicFit continuous walkthrough generation
- OMagic/MagicAI spatial model generation
- continuity, coverage, performance, provenance, and browser proof

Each indexed entry needs at least:

```json
{
  "capability_id": "stable semantic id",
  "orchestration_lane": "governed_render",
  "artifact_kinds": [],
  "consumer_products": ["propertyquarry", "chummer"],
  "provider_candidates": [],
  "status": "verified|degraded|blocked|unverified",
  "status_reason": "human-readable and bounded",
  "last_verified_at": "UTC timestamp or empty",
  "proof_refs": [],
  "quota_posture": "audit_only|build_allowed|blocked"
}
```

Rules:

- The index selects EA as the shared lane, not a particular vendor as product truth.
- Preserve historical Matterport receipts, but remove Matterport from PropertyQuarry's active primary, fallback, and launch-critical path. The supplied model link is dead and must not be retried.
- 3DVista can be `verified` only while a current same-origin browser-render receipt passes.
- MagicFit and OMagic remain `unverified` or `degraded` unless current provider receipts support the exact requested artifact family.
- Fail closed when no provider is verified. Return a useful blocked reason and a safe diorama/photo fallback; never expose a broken iframe or pretend a floorplan is a 3D render.

## 5. Provider-neutral request contract

Create a versioned contract similar to the following. Adapt names to established local models; do not weaken the fields.

```json
{
  "contract_name": "ea.governed_spatial_render_request.v1",
  "request_id": "uuid",
  "idempotency_key": "stable caller key",
  "consumer": {
    "product": "propertyquarry|chummer",
    "tenant_ref": "opaque product ref",
    "subject_ref": "opaque property or runsite ref"
  },
  "artifact": {
    "kind": "rendered_diorama|interactive_tour|continuous_walkthrough|onboarding_vignette",
    "purpose": "inspection|walkthrough|encounter_preview|first_use_gimmick",
    "locale": "en-AT"
  },
  "source_packet_ref": "signed or immutable first-party packet ref",
  "truth_refs": [],
  "evidence_refs": [],
  "spatial_plan": {
    "room_graph_ref": "immutable ref",
    "walkable_mesh_ref": "immutable ref",
    "portal_graph_ref": "immutable ref",
    "required_room_ids": [],
    "route_policy": "continuous_all_walkable_rooms",
    "start_anchor": "optional anchor",
    "end_anchor": "optional anchor",
    "allow_revisit": false
  },
  "style": {
    "style_pack_id": "versioned id",
    "room_overrides": {},
    "asset_license_policy": "verified_reuse_only",
    "brand_claim_policy": "truthful_no_affiliation_claim"
  },
  "scene_overlays": [],
  "camera": {
    "height_m": 1.62,
    "target_delivery_fps": 60,
    "minimum_effective_motion_fps": 30,
    "motion_profile": "slow_inspection",
    "cuts_allowed": false,
    "teleports_allowed": false,
    "collision_avoidance": true,
    "rotation_smoothing": true
  },
  "output": {
    "desktop": true,
    "mobile": true,
    "video_codec": "h264",
    "interactive_package": true,
    "poster_frame": true,
    "contact_sheet": true
  },
  "content_policy": {
    "rating": "general|teen_fictional_combat",
    "graphic_injury": false,
    "real_person_likeness": false,
    "minor_combatants": false
  },
  "quota": {
    "consume_quota": false,
    "maximum_provider_attempts": 0
  },
  "callback": {
    "product_event_ref": "opaque ref"
  }
}
```

Validation must reject:

- missing source, room graph, walkable mesh, or required-room list for a continuous walkthrough
- `cuts_allowed: true` for the flagship walkthrough family
- combat overlays without a Chummer-owned gameplay truth ref
- unlicensed or unknown style assets when `verified_reuse_only` is requested
- provider names, provider URLs, credentials, or raw account IDs in product truth fields
- build requests without explicit quota consumption and bounded attempt count

## 6. Compose and build endpoints

Provide two distinct operations:

1. Compose/audit: normalize the request, resolve capability posture, validate spatial/style/content inputs, estimate cost/time, and return a signed composition receipt. It must not enqueue provider work or burn credits.
2. Compose-and-build: require authorization, `consume_quota: true`, an accepted composition digest, idempotency, attempt limits, and an audit event. It may enqueue restartable provider work.

Both operations must be idempotent. Repeating a request with the same key and source/style digests must return the existing request/job rather than burn again.

The public/product projection may expose only:

- artifact kind and product-safe label
- state: `queued`, `running`, `ready`, `blocked`, `failed`, or `disqualified`
- bounded progress and ETA
- product-owned artifact URL/ref when ready
- safe reason and retry posture

Provider names, provider task IDs, account selectors, credit balances, and raw traces belong only in the private EA receipt.

## 7. Source and spatial preparation

Do not ask a video model to infer the route from unrelated listing images alone. Materialize a spatial source packet first:

- normalized floorplan with scale and orientation
- room IDs, types, boundaries, ceiling heights, and door/window portals
- walkable polygons or navigation mesh
- adjacency/portal graph
- listing-photo-to-room assignments with confidence
- stable geometry/texture anchors for every room
- balcony/terrace classification and accessibility
- inaccessible/non-walkable exclusions
- source and license provenance

The route planner must solve a continuous, collision-free route that covers 100% of `required_room_ids`. Prefer minimal revisits. If a generative provider cannot preserve a revisited room, order the route so the room is not revisited after a long branch.

PropertyQuarry's current intended route shape is:

```text
living/dining/kitchen -> balcony -> living return -> corridor -> bedroom -> bathroom -> wardrobe -> stop
```

This order exists to preserve spatial consistency while still entering every walkable room. Replace it only when a verified room graph supports a better continuous traversal.

## 8. Style packs

Style must be data, not hard-coded prompt text. A versioned style pack must contain:

- stable style ID and human label
- room-specific composition rules
- palette and material constraints
- furniture/prop catalog refs
- negative constraints
- asset license/provenance refs
- source retrieval timestamp
- provider-specific prompt compilation kept inside adapters
- visual regression references and acceptance contact sheets

### PropertyQuarry botanical maximalist

Create a style pack such as `botanical_maximalist_decorated_v1`. It should be inspired by the high-level decorating principles associated with Justina Blakeney's *Jungalow: Decorate Wild*, without copying protected layouts or claiming affiliation:

- layered, personal, maximalist rooms
- abundant healthy plants
- vivid but coherent color
- bold mixed patterns
- rattan, warm wood, ceramics, textiles, vintage/worldly accents
- furnished, lived-in rooms rather than sparse beige staging
- no people in the normal property-inspection render

Available generated seed for visual direction only:

`/home/tibor/.codex/generated_images/019f4a48-e37e-7ed1-a5c8-74a061f76c86/exec-d2205e5a-b0cd-4f1e-943a-84e2b786dea8.png`

Import it into a project-owned, versioned asset path only after recording generation provenance. Do not overwrite accepted history.

### PropertyQuarry Scandinavian/IKEA

Create a coherent whole-apartment pack such as `scandinavian_ikea_at_2026_v1`, using current IKEA Austria product truth where legally reusable geometry/assets exist:

- living/dining: BILLY, LISABO, and a current suitable sofa family such as KIVIK, VIMLE, JATTEBO, SODERHAMN, or LILLEHEM
- wardrobe: PAX with KOMPLEMENT internals
- kitchen: METOD with a coherent muted green/oak or equivalent current front family
- bathroom: ANGsJON/BACKsJON family; do not use discontinued GODMORGON as current catalog truth
- kids room: SMASTAD/PLATSA, TROFAST, MAMMUT, and LILLABO as appropriate

Use official catalog refs and retrieval timestamps. Product names may be factual catalog metadata, but do not ingest or redistribute product photography or 3D models without verified reuse rights. If a licensed exact model is unavailable, block the `real_product` claim or render clearly identified equivalent geometry; do not silently call an approximation real IKEA furniture.

The assembly scene is a separate PAX onboarding vignette. EA generates it once per style/version; PropertyQuarry decides whether to show it once per user. EA must not own the per-user `seen` state. Product behavior must:

- scope the seen key to a privacy-safe user hash and vignette version
- skip for reduced-motion users
- provide a skip control
- mark seen on completion or skip
- never replay in the normal repeat walkthrough

An interim KALLAX image exists but is not the final PAX requirement:

`/home/tibor/.codex/generated_images/019f4a48-e37e-7ed1-a5c8-74a061f76c86/exec-1ee445ee-bbb7-4d79-96f5-8008cb1bdb35.png`

### Chummer style packs

Chummer must be able to pass any approved versioned style pack without changing the core pipeline. Initial examples can include:

- corporate arcology
- abandoned industrial site
- neon street market
- high-security laboratory
- occult interior
- derelict residential block

These are product-owned style selections compiled by EA adapters. Do not bake Shadowrun-specific nouns into the shared request model.

## 9. Chummer combat overlays

Combat is a timed scene overlay on a stable route and geometry, not a separate stitched clip. The shared core must remain unaware of game rules; Chummer supplies approved encounter truth and an explicit rendered outcome.

Example overlay:

```json
{
  "overlay_id": "encounter-beat-01",
  "kind": "fictional_combat_choreography",
  "gameplay_truth_ref": "chummer-owned immutable encounter/event ref",
  "location_anchor": "room-or-route-anchor",
  "start_time_s": 18.0,
  "end_time_s": 29.0,
  "participants": [
    {"actor_ref": "opaque stable actor ref", "role": "runner"},
    {"actor_ref": "opaque stable actor ref", "role": "opposition"}
  ],
  "beats": [
    {"at_s": 18.0, "action": "take_cover", "actor_ref": "..."},
    {"at_s": 21.0, "action": "non_graphic_exchange", "actor_ref": "..."},
    {"at_s": 26.0, "action": "advance", "actor_ref": "..."}
  ],
  "provided_outcome": "bounded Chummer-owned outcome ref",
  "camera_policy": "continuous_witness_path",
  "graphic_injury": false
}
```

Hard rules:

- fictional characters only; no real-person likeness
- no graphic gore by default
- no minors as combatants
- Chummer owns initiative, actions, effects, and outcomes; EA must not simulate or rewrite rules truth
- actor identity, wardrobe, equipment, handedness, position, and room geometry remain stable across every frame
- the camera path cannot cut, teleport, clip through geometry, or jump to another scene
- scene beats may occur around the moving camera, but they cannot prevent required-room coverage unless the request explicitly narrows the route
- content rating and provider policy checks happen before quota burn

## 10. Provider adapter requirements

### 3DVista

- Treat the verified 3DVista export as PropertyQuarry's primary interactive lane.
- Import vendor export packages into a same-origin, immutable, route-backed bundle.
- Validate all referenced assets, paths, MIME types, CSP, canvas render, loading completion, retry/recovery controls, keyboard access, touch targets, and mobile framing.
- Keep the provider adapter behind the shared EA contract.
- A static diorama and accepted continuous walkthrough are safe fallback artifacts. A dead external iframe is not a fallback.

Current verified source bundle:

`luxury-residence-with-breathtaking-skyline-views-danubeflats-vienna-layout-first-742df65557`

Current proof:

`/docker/property/_completion/smoke/propertyquarry-candidate-ux-20260710/3d-browser-gate-native60.json`

Re-run the browser gate with `--providers 3dvista` after the EA integration. Do not include Matterport.

### MagicFit

- Use provider-native cumulative continuation when available; do not stitch unrelated scenes and hide joins.
- Persist private task/account refs, prompt digests, source-frame hashes, output hashes, and continuation-chain parentage.
- A technically smooth chain still fails if the apartment mutates, furniture changes, doors move, or a revisited room no longer matches.
- Never rehabilitate a disqualified artifact by changing metadata.

Current rejected artifacts:

- Old stitched 70-second family: SHA-256 starts `5a1c238`, fingerprint starts `5af4350b`. It has visible jumps and is permanently disqualified.
- Provider-native route through route-09: 100.792 seconds, final SHA-256 starts `a665e4e9`. Its all-frame delta gate passed, but the kitchen changed from black to brown on return. It is visually/spatially rejected and is not flagship evidence.

No current MagicFit output is accepted for launch.

### OMagic/MagicAI

- Keep the model/upload lane as a provider adapter behind the same request.
- Preserve source-model and upload provenance.
- Do not call it ready unless current model generation, upload, retrieval, and browser/use proof pass.
- Product-safe projections may say `3D model` or `spatial model`; they must not expose provider account details.

## 11. Continuity and performance gates

The walkthrough must pass all of the following, on the final encoded artifact rather than only intermediate clips:

- exactly one continuous shot
- cut count: 0
- teleport/scene-jump count: 0
- required-room coverage: 100%
- collision and wall/door clipping failures: 0
- stable room topology and portals: 100%
- stable furniture identity/placement across revisits
- stable people/actor identity for Chummer overlays
- no black, blank, frozen, corrupt, or repeated-frame bursts
- final delivery frame rate: 60 fps target
- effective unique motion rate: at least 30 fps; a 60 fps container made from long duplicate runs does not pass
- no duplicate-frame run longer than two frames during camera motion
- smooth rotations with bounded angular velocity, acceleration, and jerk
- all-frame continuity max-delta gate at least as strict as the existing threshold of 18
- audio, if present, must not be used to hide visual cuts and must pass sync/level checks
- desktop and mobile video decoding without overflow or layout shift

For the interactive 3D tour, record a repeatable baseline-device profile and require:

- rendered nonblank canvas
- median desktop frame rate at least 55 fps
- median mobile frame rate at least 45 fps
- no sustained frame-time spikes during rotation
- no horizontal overflow
- controls at least 44 by 44 CSS pixels
- keyboard, touch, reduced-motion, offline/retry, and back-navigation proof

If the baseline hardware cannot meet these thresholds, return a measured degraded receipt. Do not silently lower the gate.

## 12. Product bridge behavior

### PropertyQuarry

The product bridge supplies property packet, room graph, style selection, and artifact purpose. It consumes only EA's product-safe projection.

Required behavior:

- the research hero shows a rendered diorama before any floorplan crop
- the floorplan remains available in the media/plans gallery
- 3DVista is the active interactive provider path
- requesting a walkthrough produces one all-room continuous route
- style changes regenerate from the same geometry and route constraints
- the PAX assembly vignette is separate and shown once per user/version
- rejected artifacts never become default media

Exact regression URL:

`/app/research/d907fa5b6b5d7308?run_id=727428e87aa544de82d2682a79e6da16`

### Chummer

The product bridge supplies runsite geometry, style pack, encounter truth refs, explicit outcome refs, actors, and content rating. It consumes the same artifact states and receipts as PropertyQuarry.

Required behavior:

- a non-combat runsite walkthrough works without combat-specific fields
- adding a combat overlay does not fork provider orchestration
- multiple visual styles work with the same geometry and route
- the final walkthrough remains one continuous shot through all requested spaces
- rules/explain surfaces can link the rendered beat back to the Chummer-owned event refs
- provider failure returns a blocked artifact state, not invented campaign truth

## 13. Current PropertyQuarry checkpoint

Live has not been changed by this handoff session.

Candidate runtime:

- container: `propertyquarry-api-candidate`
- port: `18097`
- image: `propertyquarry-web-runtime:flagship-diorama-candidate-20260711`
- candidate database contains a copied read-only source row for the exact historical run; live DB was only read

Curated diorama:

- asset: `/docker/property/ea/app/static/property/research/d907fa5b6b5d7308-diorama.png`
- manifest: `/docker/property/ea/app/data/property_diorama_previews.json`
- asset SHA-256: `bd0fce33199f7d8a2b19e8b72d455389e9d368f06a0c4d8880a218e7e2a89e8c`
- source listing ID: `846238136`
- source candidate: `d907fa5b6b5d7308`
- source run: `727428e87aa544de82d2682a79e6da16`

Focused tests:

```text
3 passed, 688 deselected in 59.53s
```

Candidate browser proof:

`/docker/property/_completion/smoke/propertyquarry-candidate-diorama-20260711/receipt.json`

Functional diorama checks pass on desktop 1440x1000 and mobile 390x844: exact path, correct local asset, decoded image, `object-fit: contain`, Diorama badge, and no horizontal overflow. The receipt is currently marked `fail` only because Chromium reports the expected COOP warning on an untrustworthy plain-HTTP test origin. Re-run under an HTTPS or trustworthy local origin; do not waive real page errors globally.

Screenshots:

- `/docker/property/_completion/smoke/propertyquarry-candidate-diorama-20260711/desktop.png`
- `/docker/property/_completion/smoke/propertyquarry-candidate-diorama-20260711/mobile.png`

Relevant uncommitted PropertyQuarry files include:

- `ea/app/api/routes/landing.py`
- `ea/app/templates/app/property_research_detail.html`
- `ea/app/data/property_diorama_previews.json`
- `ea/app/static/property/research/d907fa5b6b5d7308-diorama.png`
- `tests/test_propertyquarry_workspace_redesign.py`
- `ea/app/api/routes/public_tours.py`
- `scripts/propertyquarry_3d_browser_gate.py`
- `scripts/propertyquarry_flagship_3d_launch_gate.py`
- `scripts/propertyquarry_magicfit_native_continuity_gate.py`
- `scripts/render_magicfit_property_flythrough.py`

The PropertyQuarry worktree is heavily dirty. Read and preserve existing changes. Do not reset, checkout, clean, or overwrite unrelated work.

## 14. Implementation sequence

1. Run `run_pipeline` in `/docker/EA`, inspect mirrored design, and identify the existing governed-render models, capability registry, artifact service, provider ledger, internal routes, and tests.
2. Confirm whether the generic spatial contract is already canonical. If not, emit the required design petition and implement only reversible EA-local scaffolding until accepted.
3. Add/verify the EA spatial capabilities in the index with receipt-derived status.
4. Add the provider-neutral request, normalized composition, digest, product-safe projection, and private receipt models.
5. Add compose-only validation with zero quota burn and exhaustive negative tests.
6. Add authorized compose-and-build with idempotency, bounded attempts, cancellation/restart state, and audit receipts.
7. Add versioned spatial source packet and style-pack registries.
8. Add route validation/coverage and scene-overlay compilation without product-specific assumptions.
9. Adapt 3DVista, MagicFit, and OMagic behind the shared provider interface. Preserve existing receipts and disqualifications.
10. Add the PropertyQuarry domain bridge and migrate active routing to 3DVista-only.
11. Add the Chummer runsite bridge and combat-overlay request compilation. Do not put game rules in EA.
12. Add continuity, spatial drift, frame-rate, rotation smoothness, browser, accessibility, recovery, and provenance gates.
13. Run every style through the complete route. Review contact sheets and videos manually as well as mechanically.
14. Deliver only accepted style videos to Telegram, with artifact hashes and receipt refs. Clearly label diagnostics; never present a rejected render as ready.
15. Deploy to an isolated candidate, run desktop/mobile E2E and failure recovery, then hold a clean 48-hour canary.
16. Perform a second hardening pass for genericity, observability, secret redaction, idempotency, and cross-product assumptions.
17. Only after all gates and canary pass, provide a launch recommendation. Promotion remains a separate authorized action.

## 15. Acceptance test matrix

At minimum, add tests for:

### Contract and governance

- compose does not burn quota
- build without explicit quota authorization is rejected
- duplicate idempotency key does not create a second provider job
- product payload containing provider URL/secret/account ID is rejected or redacted
- missing truth/evidence refs fail closed
- unverified provider cannot project `ready`
- public receipt contains no provider-sensitive fields
- private receipt includes request/source/style/output hashes and complete parentage

### Spatial and walkthrough

- disconnected required room fails composition
- route covers every required room exactly as declared
- no-cut/no-teleport contract is enforced
- collision/portal violations fail
- all-frame continuity and duplicate-frame gates fail bad fixtures
- spatial drift rejects the route-09-style mutated-room fixture
- old stitched family remains permanently disqualified
- 60 fps metadata alone cannot pass when effective motion remains 24 fps or duplicate-heavy

### Styles

- every room type resolves valid style constraints
- botanical maximalist output is furnished, layered, colorful, plant-rich, and people-free
- Scandinavian pack resolves current room-specific catalog refs
- missing asset reuse proof blocks a `real_product` claim
- PAX vignette is a separate artifact
- first-view/repeat/user-isolation/reduced-motion behavior is tested in PropertyQuarry
- Chummer can swap style packs without changing route/provider code

### Chummer overlays

- non-combat request works with empty overlays
- combat overlay requires gameplay truth and provided outcome refs
- disallowed graphic/real-person/minor settings fail before quota burn
- actor IDs and transforms remain stable in fixture sequence
- overlay does not introduce cuts or reduce room coverage
- EA does not calculate initiative, damage, or encounter outcome

### Browser and operations

- 3DVista same-origin viewer renders on desktop and mobile
- nonblank canvas and measured frame-rate thresholds pass
- loading, offline, retry, direct-open, and back-navigation recovery pass
- touch targets, keyboard use, labels, focus, reduced motion, and overflow pass
- exact PropertyQuarry research page shows diorama first
- Telegram delivery has sent/file/hash receipts for every accepted style video
- 48-hour canary contains no unresolved P0/P1, repeated render failure, quota runaway, or provenance gap

Use the focused Chummer render-lane test slice from the `ea-governed-render-lane` skill when those services are touched:

```bash
dotnet test Chummer.Tests/Chummer.Tests.csproj --filter "FullyQualifiedName~PropertyquarryApartmentVideoArtifactRequestBridgeServiceTests|FullyQualifiedName~RunsiteOrientationRequestComposerServiceTests|FullyQualifiedName~HorizonGovernedRenderRequestComposerServiceTests|FullyQualifiedName~HorizonCapabilityServiceTests" --no-restore --verbosity minimal
```

Also run the relevant EA Python unit/integration tests and PropertyQuarry's focused browser/unit gates. Discover exact local test paths with `run_pipeline`; do not assume generated receipts are equivalent to tests.

## 16. Telegram and ETA

The user wants ETA updates and accepted videos on Telegram.

Existing ETA receipt:

`/docker/property/_completion/notifications/propertyquarry-flagship-eta-3dvista-20260711.json`

It communicated 60-84 hours, dominated by the mandatory 48-hour canary. That estimate predates this EA extraction. Rebaseline after the EA agent completes the contract/capability audit, and send the revised ETA to Telegram with:

- current milestone
- blockers
- remaining machine work
- remaining human visual review
- earliest canary start and finish
- confidence range, not a single unsupported timestamp

Do not send credentials, private provider URLs, raw account IDs, or rejected videos as launch evidence.

## 17. Stop conditions

Stop and report `blocked`, with evidence, if:

- the canonical contract seam is absent and requires design approval
- no provider can meet the no-cut/all-room/spatial-stability requirement
- required source geometry or asset rights are missing
- provider policy rejects a Chummer overlay
- quota posture cannot be verified safely
- browser proof is non-deterministic after bounded retries
- implementing the bridge would require EA to own product/user/release truth

Do not call the goal complete because tests pass, a video exists, or the canary has merely started.

## 18. Required handback receipt

The EA Codex session must return:

- status and exact scope completed
- files changed by repo
- capability-index entries and their receipt-derived states
- contract version and example compose/build receipts
- provider jobs attempted and credits consumed
- artifact hashes and provenance refs
- room coverage, cut/jump count, FPS/effective-motion, rotation, and spatial-drift metrics
- desktop/mobile browser receipts
- all tests run with pass/fail counts
- all style videos and Telegram delivery receipts
- canary start/end and incidents
- assumptions, unresolved risks, and required design follow-up
- explicit statement that live was untouched, or an authorized deployment receipt if that later changes
- explicit launch recommendation: `no`, `candidate only`, or `ready for authorized promotion`

Anything less is an intermediate checkpoint, not completion.
