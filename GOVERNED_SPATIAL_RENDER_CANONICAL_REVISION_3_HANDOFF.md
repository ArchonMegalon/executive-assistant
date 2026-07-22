# Governed Spatial Render Canonical Revision 3 Handoff

Date: 2026-07-11 (Europe/Vienna)
Controller status: Revision 2 independent re-review returned `REVISE`; implementation remains blocked.
Worker status ceiling: `proposed_for_independent_re_review`
Runtime/provider/quota/build/canary/deployment/readiness authority: none

## Bound review decision

Fresh independent reviewer session:
`019f506f-9596-7892-a551-b0481cc95760`

Decision receipt:
`/tmp/GOVERNED_SPATIAL_RENDER_REVISION_2_INDEPENDENT_REREVIEW.final.md`

Receipt SHA-256:
`be2cf8b882ae2652fd5e81d22512e20731629f2ac81f80f20c0ba1d494856979`

Decision: `REVISE`

The review independently read all 18 Chummer files, verified the packet manifest `17/17`, used real `cryptography 41.0.7` Ed25519, and found:

1. P1: `key_ref` and `key_epoch` are outside signed bytes. Relabeling a valid signature to an active alias backed by the same public key can bypass revocation and misattribute the key epoch.
2. P1: key validity does not require `receipt.issued_at >= key.not_before`; a backdated receipt can verify after the key activates.
3. P1: the raw JSON boundary does not explicitly reject duplicate member names before value construction, and epoch integers are not bounded to RFC 8785's exact interoperable numeric domain.
4. P1: generic pre-execution `quota.state: blocked` structurally accepts non-null key/request/composition/authorization-binding idempotency lineage.

The prior immutable build-lineage P1 is closed and must not regress. The direct `algorithm: none`/missing-signature shape defect is closed, but the signature contract is not closed overall.

No implementation or live action is authorized by this handoff.

## Worker identity and write scope

Resume the existing canonical amendment worker only:
`019f4fbc-a589-7183-aaa6-6cae506f9c36`

Do not create a replacement worker, helper, subagent, collaborator, or reviewer. Do not use `ea-3`.

The only repository content-write scope is:

| File | Revision 3 starting SHA-256 | Required mode |
| --- | --- | --- |
| `/docker/chummercomplete/chummer-design/products/chummer/GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml` | `952526587698d892a1b0c371b6ef5c8f34f134a28d8e6373e63620b16e422b9d` | `0664` |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_PACKET.md` | `71cd2afebe2b858dd1889f56cb29be1cf85999759a5c4ffd48be626b3df384d4` | `0664` |

These are the only two files the worker may change. Preserve every other dirty byte and all other modes. Do not edit AGENTS, mirrors, tests, scripts, authority evidence, privacy policy, recipes, PropertyQuarry, EA runtime, media-factory implementation, run-services, or hub-registry. Do not create repository-local fixtures, caches, keys, reports, or artifacts.

Use `PYTHONDONTWRITEBYTECODE=1` and independently generated in-memory fixtures. The wrapper alone may write the final response to a controller-selected `/tmp` path.

## P1 correction 1: bind the signing envelope

The protected payload must bind the signing-key identity and every signature-profile selector while avoiding digest/signature self-reference.

Replace `signed_payload_scope: entire_receipt_excluding_signature` with one exact profile:

`signed_payload_scope: entire_receipt_excluding_signature_value_and_signed_payload_digest`

The signature object must remain `additionalProperties: false` and require exactly the existing profile fields plus `key_fingerprint`:

- `algorithm`: constant `ed25519`;
- `encoding`: constant `base64url_no_padding`;
- `signature_value`: canonical 86-character unpadded base64url representing exactly 64 bytes;
- `key_ref`: non-empty opaque reference;
- `key_epoch`: safe non-negative integer;
- `key_fingerprint`: SHA-256 of the exact 32-byte RFC 8032 raw Ed25519 public key encoding, format `sha256:<64 lowercase hex>`;
- `canonicalization`: constant `rfc8785_jcs`;
- `signed_payload_scope`: exact constant above;
- `signed_payload_digest`: SHA-256 digest.

Define producer and verifier construction exactly:

1. Start with the duplicate-safe parsed complete receipt, including the complete signature object.
2. Deep-copy the receipt.
3. Delete exactly `signature.signature_value` and `signature.signed_payload_digest` from the copy. Do not remove the signature object and do not remove or normalize any other member.
4. Require the remaining signature envelope to contain `algorithm`, `encoding`, `key_ref`, `key_epoch`, `key_fingerprint`, `canonicalization`, and `signed_payload_scope` with their exact schema values.
5. RFC 8785 JCS canonicalize the entire remaining receipt.
6. SHA-256 the canonical UTF-8 bytes and require exact equality with `signature.signed_payload_digest`.
7. Resolve and validate the key record as specified below.
8. Decode `signature.signature_value` as canonical unpadded base64url to exactly 64 bytes.
9. Verify Ed25519 over the same canonical bytes used for the digest.

Changing algorithm, encoding, key ref, key epoch, key fingerprint, canonicalization, payload scope, issuer, environment, receipt expiry, or any other receipt field must change signed bytes and fail digest/signature verification unless the authorized issuer signs the changed payload with an accepted key.

The digest and signature value themselves are excluded only to avoid self-reference. No second signature mode, detached provider signature, `none`, unsigned fallback, or alternate canonicalization is allowed.

## Key-registry identity and revocation invariants

The semantic verifier's authoritative key record must contain at least:

- issuer owner;
- exact environment;
- `key_ref`;
- `key_epoch`;
- `key_fingerprint`;
- algorithm `ed25519`;
- exact 32-byte public key;
- state;
- `not_before`;
- `not_after`;
- revocation state/evidence.

Require all of these invariants:

1. `(issuer, environment, key_ref, key_epoch)` identifies exactly one immutable key record.
2. `key_fingerprint` must equal SHA-256 of that record's exact 32-byte raw public key.
3. A public-key fingerprint may map to only one key identity and epoch across all issuer environments. Re-registering the same key material under another ref, epoch, alias, or environment is invalid.
4. Revocation is indexed by public-key fingerprint as well as key identity. Revoking any record for a fingerprint makes every alias or duplicate record invalid; no alias can restore it.
5. A revoked fingerprint or identity cannot return to active state. Epochs cannot be reused or moved backward.
6. Unknown, duplicate, aliased, fingerprint-mismatched, issuer-mismatched, environment-mismatched, algorithm-mismatched, revoked, not-yet-valid, expired, or otherwise non-unique records fail closed to `unverified_or_blocked` before provider or quota action.

Fixtures must prove both layers:

- changing a structurally valid key ref/epoch/fingerprint without resigning fails because those fields are signed;
- a registry containing the same public key under a second active alias is itself rejected even if an attacker can produce a newly signed alias payload;
- revocation applies to the fingerprint globally.

## P1 correction 2: exact key-validity chronology

Parse receipt and key times as offset-aware RFC 3339 instants. Require, with no validity-window backdating exception:

`key.not_before <= receipt.issued_at <= receipt.expires_at <= key.not_after`

The receipt's `issued_at` is the issuer's signing/issuance instant for this contract. The issuer may not backdate it before key validity. Existing allowed clock skew may govern comparison with verifier wall-clock time, but it must not relax the signed receipt-to-key chronology above.

At verification time the key identity and fingerprint must still be accepted and not revoked. Revocation fails closed even for a receipt signed before revocation. Receipt expiry beyond key expiry remains invalid.

Add explicit negatives for:

- receipt issued one instant before `key.not_before`;
- receipt expiry one instant after `key.not_after`;
- reversed key validity;
- revoked fingerprint under a different alias;
- key state that is active now but was not valid at receipt issuance.

## P1 correction 3: raw JSON and RFC 8785 boundary

JSON Schema validates a value and cannot detect duplicate members already discarded by a parser. The canonical semantic contract must therefore define an exact raw ingress boundary before schema validation or JCS:

1. Verifier input is the original UTF-8 JSON text/bytes for the receipt, not an untrusted already-parsed map.
2. Reject invalid UTF-8, a UTF-8 BOM, unpaired Unicode surrogates, non-JSON numeric tokens, NaN, and infinities.
3. Parse with recursive duplicate-member detection and reject any duplicate object member before constructing the authoritative JSON value. This applies at the top level and every nested object, including `signature`, `authorization`, `quota`, `idempotency`, evidence refs, and gate versions.
4. Run JSON Schema validation only on that duplicate-safe parsed value.
5. Reject any integer outside `[-9007199254740991, 9007199254740991]` before JCS. This contract currently has no floating-point fields.
6. JCS canonicalize exactly according to RFC 8785, including UTF-16 property ordering, UTF-8 output, required escaping, ECMAScript-compatible number serialization, and rejection of invalid Unicode/non-finite values.
7. An implementation that cannot access original raw receipt bytes or prove duplicate-safe parsing must fail closed; ordinary last-wins/first-wins parsing is not acceptable evidence.

Add a reusable schema definition for a safe non-negative epoch integer:

- type `integer`;
- minimum `0`;
- maximum `9007199254740991`.

Apply it to:

- `signature.key_epoch`;
- `revocation.epoch`;
- `kill_switch.epoch`.

Audit every other schema integer field and prove it is already bounded inside the exact safe range. Do not leave an unbounded integer anywhere in the receipt schema.

Required raw-byte negatives include:

- duplicate top-level `environment` with conflicting values;
- duplicate nested `signature.key_ref`;
- duplicate nested authorization or quota member;
- duplicate member with equal values, which must still reject;
- invalid UTF-8/BOM/unpaired surrogate;
- `2^53`, `2^53+1`, and larger epoch boundary behavior;
- negative epoch;
- non-finite or non-JSON numeric token;
- ordinary last-wins and first-wins parser differentials.

Required positives include Unicode strings, UTF-16 key ordering, escaped controls, safe integer boundaries `0` and `9007199254740991`, and the real Ed25519/JCS signed receipt.

## P1 correction 4: generic blocked is structurally pre-execution

For `quota.state: blocked`, add an exact idempotency shape requiring:

- `key_digest: null`;
- `normalized_request_digest: null`;
- `composition_digest: null`;
- `authorization_binding_digest: null`.

The existing `scope_digest` may remain non-null as a non-execution request-family correlation value. State explicitly that it cannot establish a job, reservation, attempt, composition acceptance, provider call, quota mutation, or build lineage.

Keep the existing quota pre-execution shape requiring no reservation, reservation expiry, mutation token, consumption receipt, compensation receipt, or attempt. Add an explicit canonical semantic rule matching the structural rule: any generic-blocked receipt carrying one of the four nullable idempotency build-lineage fields fails to `unverified_or_blocked`.

Required fixtures:

- one coherent generic-blocked positive;
- four individual non-null idempotency-field negatives;
- one all-four-fields non-null negative;
- reservation, attempt, and consumption smuggling negatives;
- all `8/8` must reject structurally and semantically;
- `not_present_audit_only` remains a separate zero-burn path and must not regress;
- all 11 actual build states continue to require complete non-null immutable lineage.

## Packet revision

Update only the existing packet to describe:

- the new signed-envelope payload construction;
- raw-key fingerprint and registry uniqueness/revocation invariants;
- exact key-validity chronology;
- duplicate-safe raw UTF-8 JSON ingress;
- RFC 8785 safe-number bounds;
- structural generic-blocked idempotency nulling;
- new positive and adversarial fixture counts.

Do not claim any runtime verifier, key registry, provider capability, provider quota, compose/build path, browser journey, FPS, tour, video, canary, deployment, or readiness proof.

After schema bytes freeze:

1. update exactly the schema hash row in the packet's 17-file manifest;
2. preserve the other 16 embedded hashes byte-for-byte;
3. recompute the packet SHA-256 with self-hash excluded as before;
4. preserve both file modes `0664`;
5. keep amendment state `proposed_for_independent_re_review`, implementation blocked, implementation authorization false, provider execution false, quota authorization false, accepted capability receipts `0`, and projection `unverified_or_blocked`;
6. do not launch the next reviewer.

## Required full regression

First reproduce the Revision 2 findings against the starting schema. Record expected pre-patch acceptance of:

- same-public-key active-alias relabel;
- receipt issued before key `not_before` but verified after activation;
- raw duplicate-key last-wins/first-wins differential;
- unsafe epoch integer acceptance;
- five generic-blocked idempotency-lineage smuggling fixtures.

Then run the complete post-patch matrix:

- duplicate-key-safe YAML for all six YAML files;
- Draft 2020-12 schema check with format checking;
- explicit raw duplicate-safe JSON parser tests;
- real deterministic Ed25519 positive and Unicode/JCS positive;
- all prior signature structural and semantic/cryptographic negatives;
- signed-envelope mutation negatives for key ref, epoch, fingerprint, algorithm, encoding, canonicalization, and scope;
- same-key alias, fingerprint reuse, global revocation, and key chronology negatives;
- safe-integer boundary positives and every unsafe-integer negative;
- all 11 build-state positives;
- `55/55` idempotency null negatives and `55/55` original-authorization null/zero negatives;
- six coherent blocked/revoked/expired terminal positives;
- all compensation-failed lineage-loss negatives;
- generic-blocked `8/8` structural and semantic smuggling rejections;
- audit-only positive;
- authorization-binding, request/composition, same-key conflict, retry/compensation, duplicate-compensation, optimistic-refund, and attempt-limit negatives;
- offset-aware RFC 3339 and freshness arithmetic tests;
- RFC 8785 Unicode, UTF-16 ordering, escaping, safe-number, invalid-Unicode, and non-finite tests;
- all 18 cross-file ownership, recipe, RUNSITE, privacy, milestone, mirror, and PropertyQuarry assertions;
- packet manifest `17/17` and all bound governing hashes;
- `python3 scripts/ai/validate_contract_sets.py` output `ok`;
- `git diff --check`;
- stale PropertyQuarry authority hits `0` and literal canonical EA alias hits `0`;
- exact known sync classifier: exit `1`, 8 missing sources, 56 expansions, 64 diagnostics, zero governed-spatial diagnostics;
- exact before/after protected-repository fingerprints and zero writes outside the two authorized files.

Harness-only corrections are allowed in memory. They must not create files or weaken expected outcomes.

## Bound authority and preserved gates

Require these evidence hashes to remain exact:

| Evidence | SHA-256 |
| --- | --- |
| governing petition decision | `2a5e4888bf2e9074a93e97e83d682e385eff53dd9c5ef8961fdc2fec6c2d1d6c` |
| PropertyQuarry authority decision | `401fe42211e2d8283ea9ca2a7cfc1a1eaffc80ff13c63fdf9e6158a116eff50a` |
| EA petition | `ed4f8452d59760e11b6ab7784c9a35d272db4d62520d6c742740573424b3f45e` |
| generated design-review receipt | `3226895f1946d519bf5be62e9795b81bd3985de383f8efa6113c4fa4a05deb2c` |
| cross-project handoff | `e6ceebaedf91ef50a9e6179ac8775bbdb684147ffe1ca3ccc72175abcf68ee06` |
| Revision 2 correction handoff | `9384185898bb18e04db80289f5c9f648b92244d7ed32e5f975ea9427ae193ab7` |
| Revision 2 worker receipt | `c3ea6ffa9925af385b670eeb9d9f387126649f66f30cd062f61c712574cd11d7` |
| Revision 2 independent re-review | `be2cf8b882ae2652fd5e81d22512e20731629f2ac81f80f20c0ba1d494856979` |

PropertyQuarry remains blocked pending its numeric product policy and independent review. MagicFit and OMagic remain unverified provider capabilities, not product truth. Matterport/3DVista/other hosted adapters, style packs, continuous walkthroughs, combat previews, mobile/browser/accessibility, effective FPS, all-room coverage, privacy/deletion, 48-hour canary, rollback, promotion, and launch remain later gates.

## Telegram binding

The controller sent the material review-decision/ETA update after the reviewer exited:

| Field | Value |
| --- | --- |
| transport | `telegram_bot` |
| bot handle | `tibor_concierge_bot` |
| message count | `1` |
| message ID | `3769` |
| observed at | `2026-07-11T09:32:50Z` |
| sent | `true` |

The worker must not seek or expose the chat reference and must send no Telegram message. Bind this controller receipt in the final worker response only.

## Repository drift and forbidden actions

EA is concurrent external drift. Never claim EA unchanged. Prove zero worker EA writes from the action log.

PropertyQuarry, established run-services path `/docker/chummercomplete/chummer.run-services`, and `/docker/chummercomplete/chummer-hub-registry` are forbidden and must remain exact. Chummer files outside the two-file write scope are read-only.

Forbidden actions:

- runtime or implementation code;
- route, adapter, API, product, or privacy implementation;
- provider/account/network lookup or call;
- upload, job, quota reservation/consumption/mutation, build, or test build;
- browser, video, tour generation, FPS run, or canary;
- deployment, publication, mirror publication, promotion, or readiness projection;
- PropertyQuarry mutation;
- Telegram or other notification;
- helper, subagent, reviewer, or replacement worker launch.

## Final worker receipt

Stop at `proposed_for_independent_re_review`. The final wrapper-captured response must include:

- exact worker session ID `019f4fbc-a589-7183-aaa6-6cae506f9c36`;
- the Revision 3 handoff hash;
- bound `REVISE` reviewer session, receipt hash, and explicit closure status for all four findings;
- exactly two changed files with starting/final hashes and modes;
- packet manifest `17/17` and proof the other 16 hashes stayed exact;
- precise independently executed fixture counts, including real Ed25519, raw duplicate JSON, signed-envelope alias, key chronology, safe-integer, generic-blocked, and all prior regression groups;
- exact contract-validator, sync-classifier, cross-file, stale-wording, and diff-check results;
- before/after protected-repository fingerprints;
- EA concurrent-drift truth and zero worker EA writes;
- Telegram delivery binding above and zero worker Telegram actions;
- zero-action counters for every forbidden class;
- exact remaining design-review, implementation, PropertyQuarry-policy, provider, runtime-journey, canary, rollback, and promotion gates;
- explicit statement that this is not implementation or launch/readiness evidence.

Do not launch the next independent review. Stop after the receipt.
