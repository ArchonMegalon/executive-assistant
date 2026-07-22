# Governed Spatial Render Canonical Revision 5 Recovery Handoff

Date: 2026-07-11 (Europe/Vienna)
Controller posture: outer EA Codex performs one bounded canonical correction
Worker delegation: superseded for Revision 5
Separation-of-duties gate: fresh independent Chummer design reviewer after this checkpoint
Maximum status: `proposed_for_independent_re_review`
Implementation, provider, quota, build, publication, promotion, and readiness authority: none

## Decision

Revision 4 worker `019f50aa-0526-79a1-8fcb-13ee4537921a` exceeded its retry budget and is permanently retired. Never resume, fork, or reuse it. Do not launch another implementation worker, helper, subagent, collaborator, `ea-3`, or reviewer during this correction.

The user explicitly authorizes the outer EA Codex to perform the bounded Revision 5 correction. This supersedes only worker delegation. Every canonical owner, authority split, forbidden-action boundary, fail-closed requirement, independent-review gate, implementation blocker, PropertyQuarry blocker, and launch/readiness blocker from Revisions 2 through 4 remains unchanged.

## Bound evidence

| Evidence | SHA-256 | Meaning |
| --- | --- | --- |
| `/tmp/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_4_WORKER.final.md` | `f0453ede69aec19f315442a719e949cae9e1badc9477ef2810c014bedf5c67ce` | Honest R4 `failed_retired` receipt; all R4 harness counts invalid |
| `/docker/EA/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_4_RECOVERY_HANDOFF.md` | `4524fe394454911f58bfda153155d8945f200d5485ad2f1b0afcfdc32cafc0bb` | R4 contract and inherited matrix |
| `/docker/EA/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_3_HANDOFF.md` | `52f77bc7db4cf28b552523deefdabf92b5aabd9244914a04d2e8e1d0d733c5aa` | Full P1 correction and authority contract |
| `/tmp/GOVERNED_SPATIAL_RENDER_REVISION_2_INDEPENDENT_REREVIEW.final.md` | `be2cf8b882ae2652fd5e81d22512e20731629f2ac81f80f20c0ba1d494856979` | Independent `REVISE` decision, reviewer `019f506f-9596-7892-a551-b0481cc95760` |
| R4 worker transcript | `4123ed39fca24d9659a1429c3b3cbf3681ad33ed722426517c8a69719b87829c` | Failure/action evidence only; do not reuse its fixtures or counts |

All governing evidence hashes listed in Revision 3 remain mandatory and exact.

## Frozen starting bytes

These are the only canonical repository files the outer controller may edit. Modes must remain `0664`.

| File | Revision 5 starting SHA-256 | Mode | Size |
| --- | --- | ---: | ---: |
| `/docker/chummercomplete/chummer-design/products/chummer/GOVERNED_SPATIAL_RENDER_CAPABILITY_QUOTA_EVIDENCE.schema.yaml` | `724c03079c41c0f0c2ea94fb89057cafe200bb7ea014cf422f7d9c5526ff2a30` | `0664` | 46816 bytes |
| `/docker/chummercomplete/chummer-design/products/chummer/review/GOVERNED_SPATIAL_RENDER_CANONICAL_AMENDMENT_PACKET.md` | `83b425f0cae35a7b9358b9e69abad0736b2d04f19dd1eaa9915f1a4e8f1581f4` | `0664` | 33983 bytes |

The schema is byte-identical to its R4 start. The packet differs from its R4 starting hash only by the schema-manifest row; replacing the one current schema hash with the old row hash in memory reproduces exact R4 starting packet hash `68dcad9f5a6fd89b53a6a2f95dcd3222f001c2a5864b6cbe2fb4f1194d81210b`.

All other Chummer files and modes are read only. Preserve all existing dirty work. No reset, clean, checkout, stash, revert, overwrite, formatting sweep, generator, or bulk rewrite.

## Edit contract

Use `apply_patch` for every content edit to either owned file. Do not use Python, shell redirection, formatter output, or a generator to write repository content.

The schema must close and explicitly state:

1. `compensation_failed_blocked` requires top-level `quota_posture: blocked`, `readiness_projection: blocked`, and kill-switch state `blocked` or `kill_switch_engaged`.
2. That terminal retains complete build lineage: non-null scope/key/normalized-request/composition/authorization-binding digests, immutable original authorization fields, snapshot, reservation, attempt, mutation, consumption, and compensation evidence.
3. `compensation_failed_blocked` is excluded from `build_allowed`, is not generic `quota.state: blocked`, and cannot be accepted with `route_allowed`.
4. Generic `quota.state: blocked` is pre-execution, keeps non-null correlation `scope_digest`, nulls all four build idempotency fields, and carries no reservation, attempt, mutation, consumption, or compensation lineage.
5. The raw JSON semantic boundary is a bounded no-float contract: recursively reject malformed UTF-8, BOM, duplicate names, invalid/unpaired Unicode, non-finite values, every floating-point token including integral-looking/exponent forms, and integers outside `-9007199254740991..9007199254740991` before schema validation or signing.
6. The signed envelope starts from a deep copy of the complete duplicate-safe parsed receipt and deletes exactly `signature.signature_value` and `signature.signed_payload_digest`. It never blanks those fields or removes any key/profile selector.
7. Key identity, raw-key fingerprint, global fingerprint uniqueness/revocation, no alias reactivation, no epoch reuse/regression, and exact zero-skew key chronology remain fail closed.
8. No field or prose projects implementation, provider capability, quota authority, artifact readiness, publication, promotion, or launch readiness.

Do not weaken any authorization, evidence-family, revocation, quota, idempotency, capability, kill-switch, privacy, ownership, retention, route, or promotion condition.

## Bounded JCS profile

The receipt contract intentionally admits no floating-point values. For this supported JSON domain, the final harness must implement and prove RFC 8785-compatible canonical bytes as follows:

1. Parse raw UTF-8 with duplicate-name detection and explicit rejection of BOM, malformed UTF-8, non-finite constants, floats, unsafe integers, and unpaired surrogates at every depth.
2. Recursively validate that each value is only object, array, valid Unicode string, safe integer, boolean, or null. Check booleans before integers because Python booleans subclass integers.
3. Sort object keys by UTF-16 code units using `key.encode('utf-16-be')`. Do not use locale collation, Python code-point ordering, or `sort_keys=True` as proof.
4. Serialize accepted string/safe-integer/boolean/null scalars with compact `json.dumps(..., ensure_ascii=False, allow_nan=False, separators=(',', ':'))`; recursively compose arrays and sorted objects without whitespace.
5. Prove known UTF-16 ordering with keys carriage-return, `1`, U+0080, U+00F6, U+20AC, U+1F600, and U+FB33 in that exact order.
6. Prove escaping for quotes, reverse solidus, control characters, newline, and non-ASCII Unicode.
7. Compare the Python bounded canonicalizer byte-for-byte with local Node `JSON.stringify` over independently sorted object structures for the supported no-float domain, including non-BMP keys, nested arrays/objects, safe-integer boundaries, booleans, and null.

The harness must not claim general floating-point ECMAScript serialization because floats are rejected by contract.

## Signature proof

Use a deterministic 32-byte Ed25519 private seed with installed `cryptography`. Derive the exact 32-byte RFC 8032 raw public key and its SHA-256 fingerprint.

For every signed receipt fixture:

1. construct the complete signature object with all required selectors;
2. deep-copy the complete receipt;
3. delete exactly `signature_value` and `signed_payload_digest` from the copied signature object;
4. bounded-JCS canonicalize the remaining receipt;
5. SHA-256 those exact UTF-8 bytes;
6. sign those same bytes with Ed25519;
7. require canonical unpadded base64url encoding of exactly 64 bytes and an 86-character value with valid terminal bits;
8. verify digest, key tuple/fingerprint/chronology/revocation, and Ed25519 over the same bytes.

Mutating algorithm, encoding, key ref, epoch, fingerprint, canonicalization, scope, issuer, environment, receipt expiry, or any payload member without a new authorized signature must fail.

## Single final harness

After intended schema bytes and non-result packet wording are frozen, run one final consolidated harness supplied through standard input. It may invoke local Node with `node -e` for parity, but it must not create any repository file, `/tmp` file, script, fixture, key, cache, bytecode, report, or generated artifact. Use `PYTHONDONTWRITEBYTECODE=1`. No package install, tool update, network, or provider call.

If that one final run is not fully green:

- do not update packet result claims;
- do not combine it with any prior run;
- record the exact failing named cases and stop;
- do not launch another worker or reviewer.

If it is fully green, update the packet with only those reproduced counts and the final schema manifest row. Then independently re-run only small controller checks that do not recreate the full harness: hashes, modes, packet row parsing, other-16 manifest hashes, governing hashes, repository fingerprints, `git diff --check`, contract validator, and known sync classifier.

## Required full matrix

The single run must emit each named case, intended rejection layer, result, and exact group tally:

- duplicate-safe YAML `6/6` and Draft 2020-12 schema plus `FormatChecker`;
- raw valid parser cases and negatives for duplicate names at multiple depths, BOM, malformed UTF-8, unpaired high/low surrogate, non-finite constants, floats (`1.0`, exponent form, negative zero), unsafe integer high/low, trailing data, and wrong root;
- bounded-JCS ordering, escaping, nested structures, safe-integer bounds, Node parity, and invalid-domain negatives;
- deterministic real Ed25519 positive and non-ASCII signed receipt positive;
- signature structural, semantic/cryptographic, and signed-envelope selector/payload mutation negatives;
- key alias, duplicate fingerprint, global revocation, no reactivation, epoch reuse/regression, unknown/mismatched key, and zero-skew chronology negatives;
- all build lifecycle states `11/11` positive;
- idempotency null negatives `55/55`;
- original-authorization null/zero negatives `55/55`;
- coherent blocked/revoked/expired build-terminal positives `6/6`, including exact `compensation_failed_blocked` blocked posture and full lineage;
- compensation-failed lineage-loss negatives `10/10`;
- generic blocked smuggling structural `8/8` and semantic `8/8`: four individual build digests, all four together, reservation lineage, attempt plus mutation, consumption plus compensation;
- audit-only positive;
- authorization-binding, request/composition mutation, same-key conflict, concurrent duplicate, retry, compensation, duplicate compensation, optimistic refund, and attempt-limit negatives;
- offset-aware RFC 3339 ordering, capability freshness, evidence expiry, authorization age, reservation lease, kill-switch/quota freshness, canary windows, and zero-skew key validity;
- all 18 cross-file ownership/recipe/RUNSITE/privacy/milestone/mirror/PropertyQuarry assertions;
- packet manifest `17/17`, exact other-16 hashes, and all governing evidence hashes;
- `python3 scripts/ai/validate_contract_sets.py` output `ok`;
- `git diff --check` success;
- stale PropertyQuarry unresolved-authority contradictions `0` and literal canonical `ea.*` contract aliases `0`;
- known sync baseline only: exit `1`, 8 missing source diagnostics, 56 mirror-expansion diagnostics, 64 total diagnostics, zero governed-spatial diagnostics;
- exact before/after repository fingerprints and no content writes beyond the two owned files.

A negative counts only if the intended validator layer rejects the intended defect while all unrelated fixture fields remain valid.

## Packet result contract

Every Revision 3 and Revision 4 harness count is invalid. Remove or explicitly supersede those claims.

On a green Revision 5 run only, the packet must record:

- R4 `failed_retired` receipt path and hash;
- this R5 handoff path and hash;
- direct outer-controller execution and no delegated implementation worker;
- exact bounded no-float JCS profile and real Ed25519 construction;
- exact named Revision 5 result counts;
- final schema hash in its manifest row;
- exact unchanged hashes for the other 16 files;
- status only `proposed_for_independent_re_review`;
- fresh independent review still required;
- explicit non-evidence for implementation, provider, quota, build, publication, promotion, launch, and readiness.

## Authority and forbidden actions

EA remains provider-redacted derived telemetry and separately authorized synthetic zero-burn compose assistance only. Media-factory owns Chummer contract/execution receipts and quota mutation. Hub owns the Chummer bridge. Registry owns publication/revocation. Fleet owns landing evidence. PropertyQuarry retains the exact external owners already bound and remains blocked pending its numeric product policy and independent re-review.

Forbidden, required count `0`:

- any content write outside the two owned Chummer files after this handoff;
- runtime or implementation code;
- PropertyQuarry mutation;
- provider/account/network/balance/credential/quota lookup or call;
- upload, provider job, reservation, consumption, cancellation, compensation, build, or test build;
- browser, video, tour, FPS, accessibility, or canary run;
- deployment, mirror/public publication, promotion, or readiness projection;
- Telegram or other notification;
- worker, helper, subagent, collaborator, or reviewer launch.

The already-sent Telegram message `3769` is historical binding only. Send none.

## Repository parity

PropertyQuarry, `/docker/chummercomplete/chummer.run-services`, and `/docker/chummercomplete/chummer-hub-registry` must remain exact. Chummer may change only in the two owned files. EA is concurrent external/controller drift and must never be called unchanged; prove no unauthorized EA changes through the direct action log and handoff-file accounting.

## Final controller receipt

Capture the bounded result at:

`/tmp/GOVERNED_SPATIAL_RENDER_CANONICAL_REVISION_5_CONTROLLER.final.md`

It must include exact hashes/modes, full one-run matrix, manifest and governing hashes, repository parity, action log, forbidden counters, R4 failure binding, and all remaining gates. It must state that independent review has not been launched and that this is not implementation or readiness evidence.

Stop at `proposed_for_independent_re_review`. Do not launch the reviewer and do not authorize implementation.
