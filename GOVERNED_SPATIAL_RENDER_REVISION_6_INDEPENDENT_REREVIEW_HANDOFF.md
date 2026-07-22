# Governed Spatial Render Revision 6 Independent Re-review Handoff

Date: 2026-07-11 (Europe/Vienna)
Status: controller-issued, fresh read-only review required
Decision ceiling: exactly `ACCEPT` or `REVISE` for design canon only
Runtime implementation authorized: no
Provider, quota, build, canary, deployment, publication, promotion, or readiness authority: none

## Mission

Perform one fresh independent adversarial review of the exact Revision 6 governed spatial-render canon. Determine whether the design contract is structurally and semantically coherent, owner-correct, cryptographically exact, fail-closed, privacy-safe, provider-neutral, style-extensible, and ready only for a separately authorized bounded implementation stage.

This is not implementation and not a continuation of any amendment worker or prior reviewer. A green controller receipt and `341/341` controller matrix are evidence to challenge, not proof to trust. The reviewer must independently reproduce coverage without reading or reusing the R5/R6 controller command, controller transcript, or any extracted harness text.

## Fresh Reviewer Identity

- Launch exactly one new independent Codex reviewer session.
- It must not be prior reviewer `019f506f-9596-7892-a551-b0481cc95760`.
- It must not be amendment worker `019f4fbc-a589-7183-aaa6-6cae506f9c36`.
- It must not be retired worker `019f50aa-0526-79a1-8fcb-13ee4537921a`.
- It must never be `ea-3`.
- Do not launch a helper, subagent, collaborator, replacement, or second reviewer.
- The reviewer has zero repository write scope.
- The wrapper may capture only the reviewer's final response at:
  `/tmp/GOVERNED_SPATIAL_RENDER_REVISION_6_INDEPENDENT_REREVIEW.final.md`

The reviewer must report its actual fresh session ID from its own CLI session and must ignore any inherited outer `CODEX_THREAD_ID`.

## Mandatory Front Door

1. From `/docker/EA`, invoke vexp `run_pipeline` first with this exact review task. If the capability is unavailable, version-blocked, degraded, empty, or returns unrelated pivots, record that once and continue only with exact named and packet-manifested evidence. Do not replace authority with search results.
2. Read `/docker/EA/AGENTS.md` and the three mirrored design front-door files when present:
   - `/docker/EA/.codex-design/product/README.md`
   - `/docker/EA/.codex-design/repo/IMPLEMENTATION_SCOPE.md`
   - `/docker/EA/.codex-design/review/REVIEW_CONTEXT.md`
3. Read `/docker/chummercomplete/chummer-design/AGENTS.md`.
4. Use only exact named or packet-manifested files. Do not grep, glob, or broadly search any repository.

## Hash-Bound Inputs

Require these exact bytes before substantive review:

| Evidence | Path | Required SHA-256 | Required mode |
| --- | --- | --- | ---: |
| Revision 6 schema | `/docker/chummercomplete/chummer-design/products/chummer/GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml` | `f86e6f737ba3333f7e84d8196481cda4c4cc34dc08d6b5aff5a7465af303546f` | `0664` |
| Revision 6 packet | `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_PACKET.md` | `874f3ce32c160d396814381cee98ad936cb53bbb15f95a5591fecf9af17f82e7` | `0664` |
| Revision 6 assertion-correction handoff | `/docker/EA/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_6_ASSERTION_CORRECTION_HANDOFF.md` | `10f8df8d40e35c1938995e804f6716fcddd6c82a022976789d38fbce7090c024` | read only |
| Revision 6 controller receipt | `/tmp/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_6_CONTROLLER.final.md` | `50b31e2e064da1668f893892e2d1479950dab5b55134dd099496f90be1ce56ff` | read only |
| Revision 5 failure receipt | `/tmp/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_5_CONTROLLER.final.md` | `816232856d60d073b845904fca153b09b14198b50fcd245fc1bf8909683dda1d` | read only |
| Revision 2 independent `REVISE` receipt | `/tmp/GOVERNED_SPATIAL_RENDER_REVISION_2_INDEPENDENT_REREVIEW.final.md` | `be2cf8b882ae2652fd5e81d22512e20731629f2ac81f80f20c0ba1d494856979` | read only |

The packet contains an exact 17-file canonical manifest and 11 governing-evidence hash rows. Recompute every listed hash directly from disk. Require manifest `17/17` and governing evidence `11/11`. Treat the packet as the eighteenth reviewed canonical Chummer file and require all 18 files to be read in full.

## Independence Order

Review in this order:

1. Verify this handoff hash supplied by the controller, the schema hash/mode, and packet hash/mode.
2. Parse and verify the packet's 17-file manifest and 11 governing-evidence rows.
3. Read the governing petition decision, PropertyQuarry authority decision, schema, packet, and all 16 other packet-manifested canonical files in full.
4. Independently write candidate P0/P1/P2 defects and the fixture plan into reasoning before reading controller result claims.
5. Read the Revision 2 `REVISE` receipt, Revision 5 failure receipt, Revision 6 assertion handoff, and Revision 6 controller receipt only after the independent candidate-defect pass.
6. Build and run a fresh in-memory adversarial harness. Do not read any controller session transcript. Do not extract, copy, transform, replay, or compare against the R5/R6 controller command or harness source.
7. Challenge every claim using independently constructed fixtures and validators.

The reviewer may cite controller counts only as claims audited after independent work. Matching the controller count is neither required nor sufficient; complete named coverage is required.

## Supported-Domain RFC 8785 Review

The contract intentionally permits only object, array, valid Unicode string, safe integer, boolean, and null values. Every float is forbidden, including finite integral-looking and exponent tokens. The fresh review must independently verify:

- strict UTF-8 raw ingress;
- BOM, malformed UTF-8, duplicate object name, trailing-data, wrong-root, non-finite, float, negative-zero token, unsafe-integer, and unpaired-surrogate rejection before schema validation or signing;
- recursive safe integer range `-9007199254740991..9007199254740991` with booleans handled separately from integers;
- object-key ordering by UTF-16 code units, not locale and not Python code-point order;
- compact, whitespace-free, `ensure_ascii=False` scalar behavior for the supported domain;
- known ordering across carriage return, `1`, U+0080, U+00F6, U+20AC, a non-BMP key, and U+FB33;
- quote, reverse-solidus, control, newline, non-ASCII, nested object/array, and safe-boundary vectors;
- byte-for-byte parity with local Node `JSON.stringify` over independently UTF-16-sorted structures in the supported no-float domain;
- fail-closed rejection rather than a false claim of general floating-point JCS support.

Use only in-memory values and local `node -e`. Do not create a Node script file.

## Signature And Key Registry Review

Use installed `cryptography` with a deterministic 32-byte Ed25519 seed. If real Ed25519 is unavailable, return `REVISE`; do not simulate it.

Independently prove:

1. The complete duplicate-safe parsed receipt is deep-copied.
2. Exactly `signature.signature_value` and `signature.signed_payload_digest` are deleted from the copy before canonicalization. They are not blanked, replaced, or accompanied by deletion of any selector.
3. Algorithm, encoding, key ref, key fingerprint, key epoch, canonicalization profile, signed scope, issuer, environment, receipt chronology, and every payload field remain inside the signed bytes.
4. The digest is SHA-256 over the exact bounded-JCS UTF-8 bytes and Ed25519 signs those same bytes.
5. Signature text is canonical unpadded base64url, exactly 86 characters, decodes to exactly 64 bytes, rejects padding and malformed lengths, and enforces canonical terminal bits.
6. Positive verification succeeds for deterministic ASCII and non-ASCII receipts.
7. Mutating any signature selector, key selector, issuer/environment, expiry, or payload member without a fresh authorized signature fails.
8. Wrong digest, wrong key, bad signature bytes, unknown key, mismatched issuer/environment, revoked key, not-yet-valid key, expired key, and receipt expiry outside key validity fail closed.

The authoritative key registry must enforce exact issuer/environment/key-ref/epoch identity, raw public-key fingerprint binding, globally unique fingerprints, global revocation, no alias reactivation, no epoch reuse, and no epoch regression. Key chronology is exact zero-skew:

`key.not_before <= receipt.issued_at <= receipt.expires_at <= key.not_after`

## Lifecycle, Lineage, And Authorization Review

The complete build-state set is:

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

Build states must retain non-null scope, key, normalized-request, composition, and authorization-binding digests plus immutable original authorization ref, issue/expiry timestamps, maximum attempts in `1..2`, and quota-limit digest. The authorization binding must cover exactly the canonical owner/ref/times/maximum/quota-limit tuple. Current authorization state must not erase original lineage.

Independently cover and report:

- coherent positive fixtures for all 11 build states;
- nulling each of five idempotency/lineage digests independently in every build state;
- nulling or zeroing each of five original-authorization fields independently in every build state;
- coherent expired, revoked, and blocked build-terminal positives with lineage retained;
- exact `compensation_failed_blocked` posture: top-level blocked posture/readiness, blocked route or kill switch, full reservation/attempt/mutation/consumption/compensation lineage, and no masquerade as generic `quota.state: blocked`;
- compensation-failed lineage-loss negatives;
- generic pre-execution `quota.state: blocked` positive with scope correlation retained and all four build idempotency fields null;
- generic-blocked structural and semantic smuggling negatives for each individual build digest, all digests together, reservation, attempt/mutation, consumption, and compensation lineage;
- audit-only positive with `not_present_audit_only`, no execution lineage, and zero-burn compose posture;
- globally coherent authorization-state shapes: `valid` has complete positive authorization evidence; `not_present_audit_only` has the exact all-null/zero shape;
- stage-specific evidence families and exact compose-validator, capability, quota-snapshot, and kill-switch proof requirements;
- attempt number never exceeding immutable authorization maximum;
- same-key conflict, concurrent duplicate, changed scope/request/composition/binding, retry under different authorization, compensation under different authorization, duplicate compensation, optimistic refund, and attempt-limit rejection;
- offset-aware RFC 3339 parsing, receipt/evidence/auth/quota/kill-switch/reservation/canary freshness and ordering.

A negative counts only when the intended validator rejects the intended defect while unrelated fixture fields remain valid.

## Cross-File And Product Boundary Review

Read all 18 canonical files and verify all ownership, recipe, RUNSITE, privacy, milestone, mirror, and PropertyQuarry claims. Explicitly test the two Revision 6 corrected predicates:

1. lowercase `PROGRAM_MILESTONES.yaml` contains literal `spatial-render` and `blocked`;
2. lowercase `sync-manifest.yaml` contains `GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml` and `GOVERNED_SPATIAL_RENDER_PRIVACY_RETENTION_POLICY.md`, and does not require the amendment-packet path.

Confirm:

- media-factory owns the Chummer contract, execution receipts, provider jobs, idempotency, immutable output manifests, and quota mutation;
- Hub owns the Chummer bridge, approved refs, permission, audience, and provider-redacted product meaning;
- Registry owns publication leases, revocation, public refs, and tombstones;
- Fleet owns execution-budget, gate, canary, rollback, and landing evidence;
- EA remains provider-redacted derived telemetry and separately authorized synthetic zero-burn compose assistance only, with no contract, product, provider, quota, or readiness authority;
- PropertyQuarry bridge owner remains `/docker/property`, package `app.product`, module `app.product.property_tour_hosting`;
- PropertyQuarry privacy lifecycle/intake/closeout owner remains `/docker/property`, package `app.api.routes`, module `app.api.routes.landing`;
- PropertyQuarry minimization dependency remains `public_tour_payloads`, and revocation/deletion execution dependency remains `property_tour_hosting`;
- PropertyQuarry implementation remains blocked pending its numeric product policy and independent review;
- the public/non-combat continuous route remains separate from the private fictional non-graphic encounter family;
- the combat family consumes immutable mechanics, initiative, action, effect, damage, and outcome refs and never calculates or mutates rules;
- public and PropertyQuarry consumers cannot receive combat overlays;
- style selection remains provider-neutral, data-driven, rights/provenance-bound, and does not treat design references as licenses;
- continuous all-walkable-room coverage has no caller exclusion escape and no cut, teleport, geometry drift, collision, duplicate-frame, or false-FPS escape;
- provider capability evidence is exact-family, environment/route/gate bound, signed, fresh, revocable, and provider-redacted at product boundaries;
- no prose, historical mention, environment variable, compose success, hosted-link presence, or controller receipt projects runtime or readiness truth.

## Repository Validators And Baseline

Independently run and report:

- duplicate-safe YAML parsing for all six manifested YAML files;
- Draft 2020-12 schema meta-validation with `FormatChecker`;
- `python3 scripts/ai/validate_contract_sets.py`, requiring exit `0` and output `ok`;
- `git diff --check`, requiring exit `0`;
- the known sync classifier only: exit `1`, 8 missing-source diagnostics, 56 mirror-expansion diagnostics, 64 total diagnostics, and zero governed-spatial diagnostics;
- stale PropertyQuarry unresolved-authority contradictions `0`;
- literal canonical `ea.*` aliases inside `governed_spatial_render_v1` `0`;
- schema and packet mode `0664`;
- exact manifest `17/17`, governing evidence `11/11`, and all 18 canonical files read;
- exact protected-repository pre/post fingerprints and zero reviewer writes.

Use `PYTHONDONTWRITEBYTECODE=1`. The adversarial harness must be supplied through standard input and create no persistent fixture, key, cache, script, report, bytecode, or generated artifact.

## Decision Rules

Return `ACCEPT` only when:

- there are no P0 or P1 findings;
- all required independently authored coverage passes;
- all hashes, modes, owners, boundaries, and chronology are exact;
- no invalid receipt, lineage loss, state masquerade, signature bypass, unsafe-number path, authority leak, or readiness overclaim remains;
- repository and action-log parity proves zero reviewer writes and zero forbidden actions.

Return `REVISE` for any P0/P1 defect, material ambiguity, bypass, missing required coverage, inconsistent hash/mode, ownership leak, invalid receipt acceptance, lineage loss, unverified cryptographic behavior, or repository mutation. P2 observations may accompany `ACCEPT` only when they are explicitly non-blocking and cannot admit invalid state or weaken an authority or promotion gate.

The reviewer cannot authorize implementation. An `ACCEPT` decision means only that a controller may consider a separate bounded implementation handoff after auditing this receipt.

## Sandbox And Recovery Procedure

1. Prefer `read-only` sandbox for the one fresh reviewer.
2. The outer controller captures all repository fingerprints after this handoff is created and before reviewer launch.
3. If the initial reviewer fails before substantive review with the known `bwrap`/`RTM_NEWADDR` host condition, retain that same fresh session identity and resume only it with bypass. Never launch a replacement.
4. Bypass changes host command viability only. The reviewer remains contractually read-only over all repositories and external systems.
5. EA may exhibit concurrent external drift. Report it honestly and distinguish it from reviewer action using hashes, fingerprints, and action logs.
6. Chummer design, PropertyQuarry, run-services, and hub-registry must remain exact. The wrapper-captured `/tmp` final response is the only permitted review output.

## Forbidden Actions

Required count `0`:

- repository edits or repairs;
- implementation, runtime, route, adapter, controller, API, provider, or product changes;
- package installation, tool update, or network lookup;
- provider/account/balance/credential/quota calls;
- upload, provider job, reservation, consumption, cancellation, compensation, build, or test build;
- browser, video, tour, FPS, accessibility, or canary actions;
- deployment, mirror/public publication, promotion, or readiness projection;
- PropertyQuarry mutation;
- Telegram or any other notification;
- helper, subagent, collaborator, replacement, or second reviewer.

Telegram message `3773` was already sent by the outer controller. It is historical binding only. The reviewer sends none.

## Final Receipt

The wrapper-captured final response at `/tmp/GOVERNED_SPATIAL_RENDER_REVISION_6_INDEPENDENT_REREVIEW.final.md` must contain:

- decision exactly `ACCEPT` or `REVISE` as the final line;
- actual fresh reviewer session ID;
- findings first, ordered P0, P1, then P2, with exact file and line references where applicable;
- explicit `none` for any empty severity class;
- exact hashes and modes for the schema, packet, this handoff, R6 handoff/receipt, R5 failure receipt, and R2 `REVISE` receipt;
- confirmation that all 18 canonical files were read in full;
- packet manifest `17/17` and governing evidence `11/11` with independently recomputed hashes;
- independently authored no-file fixture groups, named cases, exact counts, intended rejection layers, commands, and results;
- explicit RFC 8785 supported-domain and Node parity verdict;
- explicit real deterministic Ed25519, exact two-member deletion, canonical terminal-bit, envelope-mutation, key-registry/revocation, and chronology verdicts;
- explicit all-11-state, lineage, authorization, generic-blocked, compensation-failed, audit-only, evidence-family, and attempt-limit verdicts;
- explicit verdicts for the two corrected cross-file predicates;
- ownership, provider neutrality/redaction, privacy/retention, combat-family isolation, full-room route, and no-readiness-overclaim verdicts;
- validator and known sync-baseline results;
- exact repository pre/post fingerprints and zero-write action counters;
- statement that the controller command/transcript was not read or reused;
- statement that Telegram and every forbidden live action remained zero;
- remaining implementation, PropertyQuarry policy, provider evidence, runtime journey, canary, publication, promotion, and readiness gates;
- explicit statement that the decision is not implementation authorization or a launch/readiness claim.

Stop after the receipt. Do not implement, launch another session, or authorize anything.
