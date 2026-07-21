# Governed Spatial Render Revision 2 Independent Re-review Handoff

Status: controller-issued, read-only review required
Decision ceiling: `ACCEPT`, `REVISE`, or `REJECT` for design canon only
Runtime implementation authorized by this handoff: no
Provider execution, quota use, build, canary, deployment, publication, or readiness claim authorized: no

## Mission

Perform a fresh independent review of the exact Revision 2 governed spatial-render canon. Determine whether the two prior P1 defects are actually closed and whether the complete contract remains coherent, owner-correct, fail-closed, privacy-safe, style-extensible, and usable by both:

1. PropertyQuarry for provider-redacted, non-combat, continuous residential 3D tours and walkthroughs in multiple decor styles; and
2. Chummer/RUNSITE for non-combat orientation walkthroughs plus a separate private fictional combat-scene preview family that consumes immutable mechanics evidence without calculating or mutating game rules.

This is an adversarial design re-review, not an implementation task. Do not repair files while reviewing them. A green worker receipt is evidence to challenge, not proof to trust.

## Fresh-reviewer identity

- Launch one new Codex reviewer session. It must not be the amendment worker session `019f4fbc-a589-7183-aaa6-6cae506f9c36`.
- It must not reuse the prior reviewer session `019f5020-a15e-7eb0-a8fd-908875302cfd`.
- Do not use `ea-3` for spatial-render work.
- Do not launch helpers, subagents, collaborators, or a second reviewer.
- The reviewer has zero repository write scope.
- The only output is the wrapper-captured final response at:
  `/tmp/GOVERNED_SPATIAL_RENDER_REVISION_2_INDEPENDENT_REREVIEW.final.md`

## Mandatory front door

1. From `/docker/EA`, invoke vexp `run_pipeline` first with the review task. If the tool is unavailable or returns unrelated pivots, record that once; do not replace authority with search results.
2. Read `/docker/EA/AGENTS.md` and the three mirrored design front-door files when present:
   - `/docker/EA/.codex-design/product/README.md`
   - `/docker/EA/.codex-design/repo/IMPLEMENTATION_SCOPE.md`
   - `/docker/EA/.codex-design/review/REVIEW_CONTEXT.md`
3. Read the Chummer design `AGENTS.md` governing the exact files below.
4. Use only exact named or hash-manifested files. Do not grep or glob repositories.

## Hash-bound review inputs

Require these exact SHA-256 values before substantive review:

| Evidence | Path | Required SHA-256 |
| --- | --- | --- |
| corrected schema | `/docker/chummercomplete/chummer-design/products/chummer/GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml` | `952526587698d892a1b0c371b6ef5c8f34f134a28d8e6373e63620b16e422b9d` |
| corrected packet | `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_PACKET.md` | `71cd2afebe2b858dd1889f56cb29be1cf85999759a5c4ffd48be626b3df384d4` |
| Revision 2 worker receipt | `/tmp/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_2_WORKER.final.md` | `c3ea6ffa9925af385b670eeb9d9f387126649f66f30cd062f61c712574cd11d7` |
| prior independent review | `/tmp/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_INDEPENDENT_REVIEW.final.md` | `1155ab9c64d897c0f7d1795c92978cfb0d1b45cecc59f480a8baf5abf2b7d25b` |
| Revision 2 correction contract | `/docker/EA/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_2_HANDOFF.md` | `9384185898bb18e04db80289f5c9f648b92244d7ed32e5f975ea9427ae193ab7` |
| original governing decision | `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_PETITION_DECISION.md` | `2a5e4888bf2e9074a93e97e83d682e385eff53dd9c5ef8961fdc2fec6c2d1d6c` |
| PropertyQuarry authority decision | `/docker/property/PROPERTYQUARRY_GOVERNED_SPATIAL_RENDER_AUTHORITY_DECISION.md` | `401fe42211e2d8283ea9ca2a7cfc1a1eaffc80ff13c63fdf9e6158a116eff50a` |
| cross-project implementation handoff | `/docker/EA/PROPERTYQUARRY_CHUMMER_GOVERNED_SPATIAL_RENDER_HANDOFF.md` | `e6ceebaedf91ef50a9e6179ac8775bbdb684147ffe1ca3ccc72175abcf68ee06` |

The corrected packet contains a 17-file manifest. Recompute every listed hash from disk and require `17/17`. Treat the packet itself as the eighteenth reviewed Chummer file. Require mode `0664` for the corrected schema and packet.

## Independence protocol

Review in this order:

1. Read the governing decision, PropertyQuarry authority decision, corrected schema, corrected packet, and all 16 other packet-manifested Chummer files.
2. Independently identify candidate defects and write them into the reviewer's own reasoning before reading the worker's claimed results.
3. Then read the prior `REVISE` receipt, Revision 2 correction contract, worker receipt, and cross-project implementation handoff.
4. Test whether each prior P1 is closed. Do not infer closure from matching prose or fixture counts.
5. Run an independently authored in-memory fixture matrix. Do not copy the amendment worker's harness.

## P1 closure question 1: exact signature contract

The only allowed profile must be all of the following:

- algorithm exactly `ed25519`;
- encoding exactly `base64url_no_padding`;
- canonical unpadded base64url signature text of exactly 86 characters and exactly 64 decoded bytes;
- non-empty opaque `key_ref` and integer `key_epoch >= 0`;
- canonicalization exactly `rfc8785_jcs`;
- signed scope exactly `entire_receipt_excluding_signature`;
- SHA-256 digest of the exact RFC 8785 JCS UTF-8 payload;
- actual Ed25519 verification using an installed cryptographic implementation;
- exact issuer and environment key binding;
- fail-closed handling for unknown, mismatched, revoked, not-yet-valid, or expired keys and receipt expiry after key expiry;
- no `none`, generic algorithm, provider-shaped signature, alternate mode, or unsigned fallback.

Adversarially answer these questions:

1. Is removal of the whole top-level `signature` object an unambiguous canonical payload definition?
2. Because envelope metadata is excluded from the signed bytes, does schema const enforcement plus successful verification under the selected active issuer/environment key prevent algorithm downgrade, false key attribution, epoch substitution, and expiry extension? If not, report a concrete exploit as P1.
3. Are RFC 8785 object ordering, UTF-8 string handling, escaping, integer handling, rejection of non-finite numbers, and duplicate-key rejection adequately specified at the JSON boundary?
4. Is the 86-character regex canonical for all 64-byte signatures, including unused trailing bits and padding rejection?
5. Are key validity semantics exact enough to distinguish not-yet-valid, expired, and revoked keys and to bind receipt issue/expiry to key validity? Ambiguity that permits an invalid receipt is P1.
6. Does payload tampering, environment mutation, issuer mutation, key-ref or epoch mismatch, wrong digest, and cryptographic mismatch always fail to `unverified_or_blocked`?

Use installed `cryptography` Ed25519 with a deterministic in-memory key. If real Ed25519 is unavailable, return `REVISE`; do not simulate cryptography. A standards-limited in-memory RFC 8785 fixture canonicalizer is acceptable only for schema-domain values and must be labeled as such; separately inspect Unicode and numeric edge semantics in the contract.

## P1 closure question 2: immutable build lineage

The following 11 quota states are the complete build-state set:

1. `authorization_verified`
2. `reservation_held`
3. `released`
4. `attempt_committed`
5. `charge_pending`
6. `cancelled_reconciliation_pending`
7. `consumed`
8. `closed_consumed`
9. `compensation_pending`
10. `compensated`
11. `compensation_failed_blocked`

For every one of those states, independent of current capability state, authorization state, revocation, quota posture, route state, or kill switch, require non-null immutable:

- `scope_digest`
- `key_digest`
- `normalized_request_digest`
- `composition_digest`
- `authorization_binding_digest`
- original `authorization_ref`
- original authorization `issued_at`
- original authorization `expires_at`
- original `maximum_provider_attempts` in `1..2`
- original `quota_limit_digest`

The authorization-binding digest must cover exactly owner, authorization ref, issue time, expiry time, maximum attempts, and quota-limit digest using SHA-256 over RFC 8785 JCS. Current authorization state is deliberately excluded so expiration, revocation, or blocking cannot erase original lineage.

Adversarially answer:

1. Does state-based conditional coverage include all 11 states with no posture-dependent escape, especially `compensation_failed_blocked`?
2. Can capability revocation, authorization expiry/revocation, route blocking, kill-switch engagement, cancellation, release, compensation, or compensation failure null or mutate any lineage field?
3. Can the same key be reused with a changed request, composition, scope, or authorization binding?
4. Can retry or compensation move to a different original authorization?
5. Can a duplicate compensation, optimistic refund, third provider attempt, or attempt above the original maximum pass the semantic contract?
6. Does generic `blocked` remain strictly pre-execution while `not_present_audit_only` remains zero-burn and outside build?

## Required independent fixture matrix

At minimum, execute and report:

- duplicate-key-safe YAML parse for all six YAML files in the packet manifest;
- `Draft202012Validator.check_schema` with format checking;
- one structurally valid and cryptographically valid deterministic Ed25519/JCS receipt;
- payload-tamper and signature-mismatch cryptographic rejection;
- structural rejection of `algorithm: none`, absent/empty/malformed/padded/short/long signature, invalid trailing bits, wrong encoding, wrong canonicalization, wrong scope, empty key ref, negative epoch, and malformed digest;
- semantic rejection of wrong digest, key ref, key epoch, issuer ownership, environment, revoked key, not-yet-valid key, expired key, receipt expiry after key expiry, tampered payload, and wrong signature;
- positive structural fixtures for all 11 build states;
- `55/55` idempotency-lineage null negatives: five fields times 11 states;
- `55/55` original-authorization lineage null/zero negatives: five fields times 11 states;
- coherent expired/revoked/blocked terminal positives with all lineage retained;
- explicit `compensation_failed_blocked` lineage-loss negatives;
- generic pre-execution `blocked` positive and execution-lineage-smuggling negatives;
- semantic authorization-binding mutation, request/composition mutation, same-key conflict, different-original-authorization retry/compensation, duplicate compensation, optimistic refund, and attempt-limit negatives;
- explicit offset-aware RFC 3339 and freshness checks;
- all 18 cross-file ownership, recipe, RUNSITE, privacy, milestone, mirror, and PropertyQuarry assertions;
- exact packet manifest `17/17` plus corrected packet hash;
- repository contract validator, `git diff --check`, stale-authority wording checks, and the exact known sync baseline: exit `1`, 8 missing sources, 56 expansions, 64 diagnostics, zero governed-spatial diagnostics.

In-memory fixtures only. Set `PYTHONDONTWRITEBYTECODE=1`. Do not write fixture, key, cache, report, or test files into any repository.

## Cross-project product and ownership review

Confirm the shared design does not collapse into PropertyQuarry-specific or Chummer-specific runtime semantics:

- The canonical contract owner is Chummer media-factory; EA is read-only synthesis/telemetry assistance and cannot own contract, provider, quota, product, or readiness truth.
- PropertyQuarry bridge owner is exactly repo `/docker/property`, package `app.product`, module `app.product.property_tour_hosting`.
- PropertyQuarry privacy lifecycle/intake/closeout owner is exactly repo `/docker/property`, package `app.api.routes`, module `app.api.routes.landing`.
- PropertyQuarry enforcement dependency is `public_tour_payloads`; revocation/deletion execution dependency is `property_tour_hosting`.
- PropertyQuarry remains blocked pending its numeric product policy and its own independent review. Chummer and EA cannot assign, implement, authorize, restore, revoke, delete, or close PropertyQuarry work.
- Chummer's non-combat continuous walkthrough remains `runsite_continuous_walkthrough` with `spatial_orientation_no_encounter_fields` and no encounter fields.
- Chummer's combat-scene lane remains a separate private-only `runsite_private_encounter_preview` with `private_fictional_non_graphic_encounter`; it must reject public/PropertyQuarry consumers, real-person likeness, minors as combatants, gore, mechanics calculation/mutation, cuts, teleports, geometry drift, and reduced room coverage.
- Combat rendering consumes immutable Chummer mechanics, initiative, action, effect, damage, and outcome refs. The render lane never calculates or mutates game mechanics.
- Style selection is data-driven and provenance-bound so additional styles can be added without cloning the contract. Licensed IKEA-like/real catalog assets, Urban Jungle/Jungalow-inspired decor, kids-room, kitchen, bathroom, and one-per-user assembly-scene gimmicks require explicit asset rights/provenance and product-owned policy; design references alone are not licenses or runtime proof.
- Continuous walkthrough quality requires one continuous route, no scene jump, all walkable required rooms, collision-safe portal traversal, stable geometry and actors, no duplicate-frame illusion, declared and effective motion at least 30 fps, and mobile/desktop accessibility evidence.
- MagicFit and OMagic remain provider capabilities, not product truth. Provider provenance must be private and verifiable, public/product payloads must be provider-redacted, and missing/stale/wrong-family/wrong-environment/wrong-route/bad-signature capability evidence must fail closed. Historical mentions, environment variables, prose, compose success, or a broken hosted-tour link are not proof.
- Matterport, 3DVista, or another hosted-tour adapter may be used only through the governed provider route with truthful fallback semantics. A failed link is never presented as a working tour.

## Claim and status ceiling

Even an `ACCEPT` decision proves only that the corrected design contract is suitable for the next bounded implementation stage. It does not prove:

- MagicFit or OMagic availability;
- any provider account, quota, or balance;
- compose or build implementation;
- a generated tour or video;
- 30/60 fps effective motion;
- all-room continuous coverage;
- combat-scene correctness;
- browser, mobile, accessibility, recovery, or interaction quality;
- privacy deletion/takedown execution;
- 48-hour canary;
- PropertyQuarry numeric policy;
- deployment, publication, launch, flagship, gold, or production readiness.

Accepted current capability receipts remain `0`, and legal projection remains `unverified_or_blocked` until later runtime evidence says otherwise.

## Decision rules

Return `ACCEPT` only when:

- both prior P1 defects are closed by structural and semantic contract evidence;
- no new P0 or P1 finding remains;
- all required independent fixtures and cross-file checks pass;
- hashes and ownership boundaries are exact;
- the packet makes no implementation or readiness overclaim.

Return `REVISE` for any material ambiguity, bypass, missing adversarial coverage, inconsistent hash, ownership leak, or contract defect that can admit an invalid receipt or lose build lineage. Return `REJECT` for an irreconcilable authority or architecture conflict. Non-blocking P2/P3 observations may accompany `ACCEPT`, but must be explicit and must not conceal a release blocker.

The reviewer cannot authorize implementation. After `ACCEPT`, the controller must issue a separate bounded implementation handoff and preserve every PropertyQuarry, provider, quota, canary, and promotion gate.

## Sandbox and write-safety procedure

1. Prefer a read-only sandbox for the fresh reviewer.
2. Before launch, capture byte-safe fingerprints for `/docker/EA`, `/docker/chummercomplete/chummer-design`, `/docker/property`, `/docker/chummercomplete/chummer-run-services`, and `/docker/chummercomplete/chummer-hub-registry` using optional Git locks disabled. Include HEAD, tracked/index diff digest, status digest, and target-file hashes.
3. If the host read-only sandbox fails before review because of the known `bwrap`/`RTM_NEWADDR` host limitation, retain the same newly created reviewer session identity. Resume that same session with bypass, never create a second reviewer, and bind pre/post fingerprints plus the action log proving zero writes.
4. EA may exhibit concurrent external drift. Report it honestly and prove zero reviewer EA writes; never claim EA unchanged when fingerprints differ.
5. PropertyQuarry, run-services, and hub-registry are forbidden and should remain exact. Chummer design is read-only for this reviewer.
6. No Telegram message is authorized for this re-review.

## Forbidden actions

No repository edit, schema repair, runtime implementation, route/adapter/API change, provider or account call, network lookup, upload, quota mutation, build, browser run, video generation, canary, deployment, publication, mirror publication, promotion, readiness projection, PropertyQuarry mutation, or Telegram action.

## Final receipt

The final response captured at `/tmp/GOVERNED_SPATIAL_RENDER_REVISION_2_INDEPENDENT_REREVIEW.final.md` must include:

- reviewer decision exactly `ACCEPT`, `REVISE`, or `REJECT`;
- fresh reviewer session ID;
- exact schema, packet, handoff, prior-review, worker-receipt, and governing evidence hashes;
- confirmation that all 18 Chummer files were reviewed and packet manifest was `17/17`;
- findings first, ordered P0 through P3, with exact file and line references;
- explicit closure verdict for each prior P1;
- exact fixture counts and command/check results, including real Ed25519 verification;
- explicit analysis of signature-envelope scope, RFC 8785 edge semantics, key lifecycle, and all 11 lineage states;
- cross-project extensibility, combat-family isolation, provider fail-closed, privacy, and ownership verdicts;
- repository pre/post fingerprints and zero-write action counters;
- EA concurrent-drift truth if observed;
- statement that no Telegram or forbidden live action occurred;
- exact remaining implementation, PropertyQuarry policy, provider proof, runtime journey, canary, and promotion gates;
- an explicit statement that the review is not a launch/readiness claim.

Stop after the receipt. Do not implement or launch another session.
