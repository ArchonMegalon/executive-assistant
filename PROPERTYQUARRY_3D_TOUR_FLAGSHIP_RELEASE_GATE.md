# PropertyQuarry 3D Tour Flagship Release Gate

Date: 2026-07-13 (Europe/Vienna)

State: `blocked_upstream_not_launch_ready`

EA release-lane implementation: `implemented_and_locally_verified`

PropertyQuarry generation, promotion, and public deployment: `blocked`

## Decision

Do not promote the current generated reconstruction as a flagship 3D tour.
EA now has a fail-closed viewer/video publication lane, but EA is not the
renderer or the `propertyquarry.com` release authority. PropertyQuarry must
produce and promote a new provenance-bound bundle through its governed
execution bridge before this gate can pass.

This is a release decision, not a claim that generation is absent. The current
viewer is interactive and the public guided-tour layout is coherent. Its
spatial output is still visibly proof-grade: placeholder-like photo panels,
very low-detail geometry, and source provenance rooted in test/tmp paths.

## Current production receipt

Observed at `2026-07-13T06:18:06Z`:

- `https://propertyquarry.com/tours/maisonette-with-balcony-layout-first-c3d1b14c44`
  returns HTTP 200 from the PropertyQuarry/Cloudflare deployment.
- Its public JSON advertises the generated walkthrough video.
- The walkthrough loads and reports 30 seconds of media.
- The reconstruction proof reports 612 rendered triangles and 5.15 percent
  projected photo coverage.
- Its reconstruction manifest refers to `/tmp/pytest-of-*` source paths.
- It has no `generated_viewer_release` and no digest-bound `video_release`.
- EA's production-mode loopback surface now omits that video and viewer, returns
  a typed 404 for the unreleased media, and keeps a truthful still-image
  fallback available.

The public-domain behavior is therefore an open PropertyQuarry deployment
blocker even though the EA boundary is closed.

## Ownership and missing execution bridge

The audited EA paths do not generate `reconstruction.json` or viewer-v3
packages. EA currently owns request normalization, authorization, quota and
privacy policy, evidence validation, release gating, and safe delivery. Its
governed build path delegates to `GovernedExecutionAdapter`, while the current
PropertyQuarry execution adapter is intentionally unimplemented.

The smallest truthful implementation is one
`PropertyQuarryGovernedExecutionBridge` in the PropertyQuarry-owned runtime:

1. Load the sealed, authorized source material without exposing it in public
   manifests or logs.
2. Build the typed prebuild/allocation request from PropertyQuarry truth.
3. Dispatch the request to the authoritative PropertyQuarry/media renderer.
4. Require signed execution, artifact, source-provenance, and quality evidence.
5. Return only an output digest plus an opaque output-manifest reference to EA.
6. Register the complete immutable viewer bundle and video, if any.
7. Promote only after the release contracts and browser/visual gate below pass.

Do not add a second renderer to EA and do not let a public route invoke a
provider directly.

## Mandatory generated-viewer release contract

`generated_viewer_release` must satisfy
`ea.public-tour-generated-viewer-release.v1` and bind exactly, with no extra
paths:

- the viewer HTML document;
- the reconstruction JSON as proof-only, never as a served asset;
- the floorplan texture;
- both pinned viewer modules; and
- every public photo texture.

Every binding requires its exact path, role, MIME type, byte size, and SHA-256.
The release also requires browser, source-provenance, publication-authority,
security, and accessibility receipt SHA-256 values; all corresponding verified
booleans; a stable release revision; truthful synthetic disclosure; and
terminal revoke/disqualify handling.

Runtime delivery additionally rejects:

- symlinks and containment escapes;
- mode drift from `0755` directories and `0644` files in the offline verifier;
- byte/hash drift;
- extra or missing bindings;
- test, debug, probe, `/tmp`, or `/var/tmp` source provenance;
- direct requests for the proof-only reconstruction JSON; and
- a viewer frame with same-origin authority.

## Mandatory generated-video release contract

Generated walkthroughs must use `ea.public-tour-video-release.v1`; route
coverage metadata alone is not release evidence. The release must bind:

- provider, video path, SHA-256, and byte size;
- quality-review and publication-authority receipts;
- the exact reconstruction-manifest SHA-256;
- a source-provenance receipt;
- provider-output, quality, publication, and provenance-review booleans;
- a release revision and exact truthful disclosure; and
- explicit `synthetic=true`, `verified_provider_capture=false`, and
  `satisfies_verified_tour_gate=false` truth flags.

Revocation or disqualification returns terminal HTTP 410. Missing/unreviewed
release evidence stays unadvertised and returns HTTP 404. Asset or provenance
drift returns HTTP 410.

## Flagship visual and interaction acceptance

A reviewer must reject the bundle if any item below fails:

- No placeholder panels, blank texture regions, debug labels, or synthetic
  room geometry that visually contradicts the source floorplan.
- Every intended photo texture loads, is mapped to a defensible room/route
  context, and remains legible at desktop and mobile sizes.
- The full source-classified walkable-room set is represented; exclusions are
  source-provenanced rather than silently omitted.
- Overview, dollhouse, room focus, guided route, orbit, zoom, pointer drag,
  keyboard use, focus visibility, reduced motion, and WebGL fallback are
  reviewed on current Chromium plus one independent browser engine.
- Desktop and narrow mobile captures have no blank stage, clipped controls,
  horizontal overflow, illegible text, or layout shift that hides the primary
  action.
- Browser console, page, and required-asset network errors are empty.
- The isolated iframe has exactly `sandbox="allow-scripts"`; cookie,
  local-storage, and parent-DOM access remain unavailable.
- The disclosure remains visible outside the canvas and never describes the
  generated reconstruction as a captured/provider-verified scan.
- If a walkthrough video is published, its visual review covers every route
  stop, not only duration/readiness metadata.

## EA verification receipts

Run inside the EA API container so the protected shared volume is readable:

```sh
python /app/scripts/verify_public_tour_generated_viewer_release.py \
  --bundle-dir /data/public_property_tours/<slug> \
  --base-url https://propertyquarry.com \
  --slug <slug>
```

The command is read-only, emits one deterministic JSON receipt, and exits
nonzero for any blocker. A local policy pass is necessary but not sufficient:
the same revision and digests must pass against the final public origin.

Focused EA regression state at this handoff: `130 passed` in one combined
release, quarantine, scene-less renderer, registration, permission, repair,
and verifier run before the final runtime restart. The suite must be rerun and
recorded again during PropertyQuarry promotion.

## Promotion sequence

1. Implement the PropertyQuarry execution bridge behind the established
   governed adapter boundary.
2. Generate a new bundle from durable, rights-reviewed sources.
3. Run structural, source-provenance, security, accessibility, browser, and
   visual review; persist immutable receipts.
4. Write the release objects atomically in the PropertyQuarry-owned publisher.
5. Verify the protected local bundle with the EA verifier.
6. Deploy PropertyQuarry without reusing the current proof manifest.
7. Verify the public page, JSON projection, every served binding, desktop and
   mobile interactions, and revocation behavior.
8. Promote only if both the EA and PropertyQuarry launch gates report no P0/P1
   blockers.

Rollback is immediate and fail-closed: set `revoked=true` or remove the ready
release object, retain the truthful still/floorplan fallback, and investigate
without serving the failed asset.
