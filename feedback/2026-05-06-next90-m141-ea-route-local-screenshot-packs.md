# Next90 M141 EA route-local screenshot packs

Implemented the EA-owned milestone `141` packet for the direct translator/import parity slice.
Package: `next90-m141-ea-compile-route-local-screenshot-packs-and-compare-packets-for-translator-x`

What landed:

- `scripts/materialize_next90_m141_ea_route_local_screenshot_packs.py` now compiles a route-local packet for `menu:translator`, `menu:xml_editor`, `menu:hero_lab_importer`, and `workflow:import_oracle` from the live compare-pack contract, UI direct-import proof, screenshot review jobs, parity-audit rows, Fleet closeout gate, and deterministic core import receipts.
- `scripts/verify_next90_m141_ea_route_local_screenshot_packs.py` fail-closes the generated packet if any route or family rows drift from the direct parity receipts, if screenshot packs disappear, or if the package metadata stops matching the canonical `141.4` EA assignment.
- The packet now pins the live canonical queue frontier and records stable row fingerprints for the design queue row, Fleet queue row, registry task row, and `desktop_client` readiness slice, so unrelated generated-at churn in upstream proof files does not reopen the EA packet.
- The packet now records the canonical `141.4` identity directly across the design queue row, Fleet queue row, and registry work-task row, including milestone `141`, wave `W22P`, and repo `executive-assistant`, so stale run briefs cannot masquerade as a new EA assignment.
- The generated packet and markdown summary now pin that the current canonical frontier is `2732551969`, so future shards follow the live design/Fleet queue rows instead of stale assignment IDs from older handoff text.
- The feedback note and markdown summary now state the same authority rule directly: stale handoff or assignment frontier snippets are not authority, and only the live canonical queue rows plus the approved local mirror can identify the active `141.4` frontier for this EA slice.
- The `desktop_client` readiness fingerprint now keys off the stable readiness contract (`status`, `summary`, and `reasons`) instead of freshness counters and generated timestamps, so routine proof-age churn does not drift the route-local packet between identical evidence runs.
- The packet and verifier now fail closed if the design queue, Fleet queue, or registry task stop resolving to exactly one canonical `141.4` row, and they also reject design-versus-Fleet queue fingerprint drift so repeated shards cannot satisfy proof with duplicate or diverged package rows.
- The packet, verifier, and tests now also pin the approved local mirror posture: the mirrored queue row and mirrored registry work-task row for `141.4` must stay aligned with the canonical queue and registry rows, so the package fails closed if the repo-local mirror drifts.
- `docs/chummer5a_parity_lab/NEXT90_M141_ROUTE_LOCAL_SCREENSHOT_PACKS.generated.yaml` and `.md` are the reproducible route-local outputs for this slice.
- `tests/test_next90_m141_ea_route_local_screenshot_packs.py` keeps the route ids, family ids, queue alignment, and bounded-closeout posture pinned.

Intentional boundary:

- This packet compiles the EA-owned route-local screenshot and compare evidence only.
- It does not mark the canonical queue rows complete while the design queue and Fleet queue remain `not_started` and the upstream registry task row for `141.4` still omits an explicit completion status.
- The approved local mirror is now aligned for both the queue row and the mirrored registry work-task row, but that mirror alignment is evidence only and does not let EA mark the canonical queue or registry rows complete.
- The downstream Fleet M141 closeout gate stays green, but that green downstream gate is not treated as permission for EA to close the canonical queue or registry rows locally.
- duplicate queue or registry rows fail closed, and that canonical row fail-closed posture applies to the design queue, Fleet queue, registry task, and approved local mirror instead of treating duplicate or drifted package rows as acceptable closure evidence.
