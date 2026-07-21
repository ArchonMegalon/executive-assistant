# Governed spatial-render privacy, retention, deletion, and takedown policy

Policy ID: `GOVERNED_SPATIAL_RENDER_PRIVACY_RETENTION_POLICY`

Amendment state: `proposed_for_independent_re_review`

Disposition remains: `revise`

Implementation state remains: `blocked`

Implementation authorized: `false`

Provider execution authorized: `false`

Quota reservation or consumption authorized: `false`

Release or public-claim scope widened: `false`

## Purpose and precedence

This policy supplies the numeric privacy, retention, deletion, takedown, legal-hold, and restoration rules for `governed_spatial_render_v1`, `runsite_continuous_walkthrough`, and `runsite_private_encounter_preview`.
It narrows `PRIVACY_AND_RETENTION_BOUNDARIES.md`; the stricter rule wins.
It does not authorize implementation, live inputs, provider access, builds, quota use, publication, or readiness.

The public RUNSITE meaning remains spatial orientation without combat, tactical, VTT, or live-mechanics claims.
The private encounter preview is a separate Chummer-only recipe and is never PropertyQuarry input.

## Data minimization and authority

Hub owns Chummer purpose, consent/authority, private audience, source-record truth, subject/takedown intake, and user-visible closeout.
Hub passes opaque least-privilege refs and approved immutable packets, not raw campaign databases or credentials.

Media-factory owns provider-payload minimization, encrypted private execution receipts, render derivatives, immutable output manifests, lifecycle/deletion execution, provider-deletion attempts/evidence, and deletion tombstones.

Registry owns public artifact publication leases, serving eligibility, renewal, revocation, public refs, and public-ref tombstones.

EA may retain only explicitly authorized provider-redacted derived telemetry or synthetic compose fixtures.
It may not retain source packets, provider task/account refs, provider traces, private execution receipts, private audience truth, quota mutations, or readiness truth.
Any EA derived-telemetry cache is purpose-bound to a bounded operator status view and restricted to the `CONTRACT_SETS.yaml` `governed_spatial_render_v1.provider_redacted_projection.allowed_fields` allowlist: artifact family, safe state, bounded progress, safe reason, retry posture, and immutable output-manifest ref.
It uses the encryption and least-privilege rules below and has a hard maximum of 24 hours from derived receipt creation; renewal is forbidden and a later derivation cannot extend an older cache record.
EA deletes the cache at expiry; `executive-assistant` owns the cache-deletion receipt while media-factory remains the sole provider-run receipt owner.
Synthetic compose fixtures are synthetic-data-only, process-local, non-authoritative, and retained for at most 1 hour or process exit, whichever occurs first.

PropertyQuarry remains an external product authority.
The verified decision `/docker/property/PROPERTYQUARRY_GOVERNED_SPATIAL_RENDER_AUTHORITY_DECISION.md` at SHA-256 `401fe42211e2d8283ea9ca2a7cfc1a1eaffc80ff13c63fdf9e6158a116eff50a` records:

* product bridge: repo `/docker/property`, package `app.product`, module `app.product.property_tour_hosting`
* privacy lifecycle, subject/takedown intake, and user-visible closeout: repo `/docker/property`, package `app.api.routes`, module `app.api.routes.landing`
* minimization and redaction enforcement dependency: `public_tour_payloads`
* revocation and deletion execution dependency: `property_tour_hosting`

Chummer records but cannot assign, implement, authorize, operate, restore, revoke, delete, or close work for those external owners.
This Chummer numeric policy is not the required numeric PropertyQuarry product policy and cannot substitute for it.
PropertyQuarry implementation remains blocked pending that product policy and independent re-review.

Provider credentials, secrets, raw access tokens, raw account identifiers, private provider URLs, and unrelated personal data are prohibited from source packets, truth refs, product projections, logs, screenshots, and public receipts.
If detected, they are quarantined from serving and deleted within 24 hours; the incident retains only a redacted digest and bounded evidence.

## Numeric retention schedule

All periods are maxima, not targets.
Deletion may occur earlier when purpose ends, consent or authority is revoked, a source/license is withdrawn, a takedown is accepted, or a narrower product rule applies.
No missing state, missing provider default, or silent renewal may extend a clock.

| Data class | Maximum active retention | Terminal, expiry, or withdrawal action |
| --- | ---: | --- |
| Raw provider request/response bodies, callback bodies, diagnostic traces, and provider task/account detail | 7 days after the provider attempt reaches a terminal state | Delete raw bodies/traces; retain only redacted hashes and the private receipt fields required below. Secrets or prohibited content delete within 24 hours. |
| Failed, rejected, cancelled, or disqualified input copies | 72 hours after terminal state | Delete input bytes and derivatives; retain a redacted failure digest and deletion receipt. Secrets or prohibited content delete within 24 hours. |
| Successful media-factory source packets and normalized provider payloads, including compose-only packets | 30 days after first packet creation or compose acceptance, whichever occurs first | Delete packet/payload bytes after manifest and provenance hashes are fixed. Build authorization, build start, retry, or terminal state never restarts or extends this clock; product-owned source records remain under their product policy. |
| Rejected, superseded, disqualified, or unpublished previews | 14 days after creation or terminal state, whichever expires first | Disable access, delete preview and derivative bytes, purge indexes/caches, and append a tombstone. |
| Private encounter previews | 30 days after creation or 7 days after the associated run closes, whichever expires first | Revoke audience access and delete preview/derivative bytes; earlier takedown, consent, permission, or source revocation wins. |
| Encrypted private execution, quota, compensation, deletion, and provider-deletion receipts | 400 days after job terminal state | Delete provider-private detail; preserve only non-sensitive aggregate compliance proof when another canon explicitly requires it. |
| Private or never-published immutable output manifests, origin/provenance records, revocation history, and deletion tombstones | 400 days after the first manifest or tombstone is created | Delete the provider-redacted private history after the maximum. Later lifecycle events, closeout, retry, restoration, or silence never restart the clock; 400 days exceeds the 35-day backup window needed for non-resurrection. |
| Published spatial artifact authorization and served bytes | 365 days per explicit Registry publication lease | Explicit owner and Registry renewal is required before expiry. Without renewal, Registry revokes serving; caches purge within 15 minutes and hot artifact/derivative bytes delete within 72 hours. |
| Immutable manifest, origin/provenance record, publication/revocation history, and deletion tombstone after public withdrawal | 548 days after withdrawal or lease expiry | Delete private/provider detail at its shorter TTL; retain only the provider-redacted append-only history needed for audit and non-resurrection. |
| Private render/source caches and temporary transcodes | 24 hours from creation | Purge automatically; on revocation or takedown, purge within 15 minutes. |
| EA provider-redacted derived-telemetry cache | 24 hours from derived receipt creation | Delete automatically with an EA-owned cache-deletion receipt; no renewal, provider-private field, source packet, audience truth, quota mutation, or readiness state is allowed. |
| EA cache-deletion receipts | 180 days from cache deletion | Delete the receipt after the maximum; it may contain only cache-record digest, allowlist/version, purpose, deletion timestamp/result, and no source, audience, provider-private, quota, or readiness data. |
| EA synthetic compose fixtures | 1 hour from fixture creation or process exit, whichever occurs first | Delete process-local fixture data; live identifiers, provider calls, provider receipts, durable acceptance digests, and quota state are forbidden. |
| Signed preview or artifact access URLs | 15 minutes from issuance | Expire without refresh; a refresh rechecks current audience, publication, revocation, and tombstone state. |
| Private access-audit logs | 180 days from access event | Delete raw actor/IP detail or collapse into a bounded security aggregate with no source/media content. |
| Encrypted rolling backups containing governed spatial data | 35 days from backup creation | Age out automatically; deletion tombstones must be replayed before any restored store opens. |

A build job that has not reached an ordinary terminal state within 14 days is treated as `blocked_terminal_for_retention` and its retention clocks start then.
A provider callback or missing status may not suspend retention indefinitely.

Published artifacts do not renew by continued traffic, provider availability, silence, or an unchanged Registry row.
Renewal requires a new, time-bounded publication authorization and a current rights, privacy, provenance, capability, quality, and takedown posture.

## Encryption and access control

Private data must use TLS 1.2 or newer in transit and AES-256-GCM or an equivalently reviewed authenticated encryption scheme at rest.
Keys must be environment-scoped, held outside artifact/source records, rotated at least every 90 days, and immediately rotated after a confirmed key exposure.

Access is least-privilege, role-bound, authenticated, and audited:

* Hub product/privacy roles may inspect approved source, purpose, permission, audience, and closeout state, but not raw provider traces or quota/provider account detail
* media-factory execution/privacy roles may inspect the minimum provider-private detail needed for execution, incident response, deletion, and accounting
* Registry publication roles may inspect provider-redacted immutable manifests, rights/provenance decisions, publication leases, revocation, and tombstones
* Fleet may inspect redacted gate, execution-budget, canary, rollback, and landing evidence, but not mutate quota or retrieve raw campaign/provider payloads
* EA receives provider-redacted derived telemetry only and has no standing access to private source, audience, receipt, provider, or quota records

Private encounter previews require an explicit campaign-membership allowlist, authenticated access, a 15-minute signed URL, and re-authorization on every refresh.
An obscure URL is not an audience control.
Public, cross-campaign, anonymous, or PropertyQuarry access is forbidden.

## Deletion cascade

The earliest of retention expiry, source deletion, consent/authority withdrawal, audience loss, license withdrawal, takedown acceptance, publication expiry/revocation, provider-route revocation, or product closeout starts one deletion cascade.

1. Hub blocks new consumer authorization and projects `blocked` or unavailable without exposing provider detail.
2. Registry revokes any public serving ref and appends a public-ref tombstone.
3. Hub revokes private audience grants and signed-link refresh.
4. Media-factory blocks new builds, cancels or reconciles active attempts without assuming a refund, purges caches within 15 minutes, and deletes hot source, preview, output, transcode, derivative, and index bytes within 72 hours.
5. Media-factory sends provider-side deletion requests within 24 hours when the provider held a copy, then stores a private deletion-evidence or unresolved-failure receipt.
6. EA deletes any authorized derived telemetry for the artifact within 24 hours and may retain no source or provider-private copy.
7. Backup tombstones prevent resurrection immediately; encrypted backup bytes age out within 35 days.
8. Hub issues Chummer user-visible closeout after media-factory and Registry receipts arrive, or reports the bounded unresolved provider/backup status by the SLA below.

Deletion cascades include every output variant, poster, thumbnail, contact sheet, preview, transcode, subtitle/audio derivative, index entry, cache key, signed URL, provider copy, and publication ref derived from the deleted source or artifact.
An immutable manifest stays append-only only as a provider-redacted tombstone/history record for its numeric maximum: 400 days for private/never-published history or 548 days after public withdrawal/lease expiry.
Immutability is not permission to retain artifact bytes or history indefinitely.

## Provider deletion evidence

Provider-side deletion evidence is private execution evidence owned by media-factory.
It must contain the provider-route digest, artifact/source/output digests, deletion request timestamp, bounded result state, evidence ref/hash, retry lineage, and final unresolved reason when proof cannot be obtained.
It must not expose a provider URL, credential, raw account identifier, or raw task identifier in product or design projections.

The provider deletion request must be issued within 24 hours of cascade start.
Deletion evidence, or an explicit unresolved-failure receipt that blocks the route for private data, is due within 7 days.
A provider that cannot honor deletion or produce bounded evidence is ineligible for private encounter inputs and projects `blocked` for that family.

## Takedown service levels

| Takedown step | Maximum time from validated intake |
| --- | ---: |
| Acknowledge request and issue case ref | 4 hours |
| Suppress public/private serving and new signed links | 4 hours |
| Purge caches after suppression state is recorded | 15 minutes |
| Send provider deletion request when applicable | 24 hours |
| Delete hot source/artifact/preview/derivative/index bytes | 72 hours |
| Produce provider deletion evidence or explicit blocked unresolved receipt | 7 days |
| Give the requester user-visible closeout or bounded unresolved status | 7 days |
| Age deleted bytes out of rolling backups | 35 days |

Hub owns Chummer takedown intake and user-visible case status.
Media-factory owns execution of artifact/provider deletion and private deletion receipts.
Registry owns public suppression, revocation, and tombstones.
No legal hold, provider failure, quota dispute, or backup cycle permits continued serving after suppression.

## Legal holds

A legal hold preserves evidence; it never preserves publication, private audience access, signed links, or provider readiness.

Every hold requires:

* case and legal-authority refs
* named product privacy owner and legal approver
* exact data-class, artifact, source, and digest scope
* reason and access-role allowlist
* `issued_at` and `expires_at`
* a deletion action for expiry or release

One hold authorization lasts at most 90 days and must be reviewed every 30 days.
Renewal requires a new explicit authorization before expiry; silence does not renew it.
At expiry or release, deletion resumes and held copies are deleted within 72 hours.

Held evidence lives in a separate encrypted evidence vault with the same access logging and key rules.
Credentials, access tokens, unrelated personal data, and served artifact links may not be placed on hold.
If a narrower evidentiary extract suffices, raw source/provider bodies must still follow their ordinary shorter TTL.

## Backup and restoration posture

Backups are encrypted, environment-scoped, rolling, and limited to 35 days.
They are for disaster recovery, not archival retention or product rollback.
Every restore must apply deletion, revocation, audience, publication-expiry, and legal-hold tombstones before the restored data is readable or served.

Restoration never re-enables a build, provider route, publication ref, private audience grant, or readiness projection automatically.

* media-factory may execute a technical restore but cannot authorize product access or publication
* private Chummer restoration requires Hub product and privacy authority plus a fresh consumer authorization
* public restoration additionally requires Registry publication authority and a new publication lease
* Fleet may verify a restore/rollback receipt but cannot authorize serving or mutate quota
* EA has no restoration authority
* for PropertyQuarry, repo `/docker/property`, package `app.api.routes`, module `app.api.routes.landing` is the recorded privacy authority that may authorize restoration only under its future approved numeric product policy and independently auditable authorization
* `public_tour_payloads` may enforce minimization/redaction and `property_tour_hosting` may execute revocation/deletion, but neither dependency may change policy, self-restore, authorize access, or close a privacy case
* Chummer, Registry, media-factory, Fleet, and EA have no authority to authorize or execute PropertyQuarry restoration or closeout

An artifact deleted for takedown, consent/permission loss, source deletion, or license withdrawal may not be restored for serving.
It requires a new approved source packet, new authorization, new idempotency scope, and a new governed build after all gates are independently authorized.

## Product closeout owners

| Closeout concern | Owner | Boundary |
| --- | --- | --- |
| requester intake, private audience/access, product-safe reason, user-visible status | `chummer6-hub` | consumes deletion/publication receipts; no provider-private detail or quota mutation |
| artifact/source/derivative/provider deletion, private receipt, tombstone evidence | `chummer6-media-factory` | executes deletion; does not authorize product access or public restoration |
| public withdrawal, publication expiry/revocation, public-ref tombstone | `chummer6-hub-registry` | no provider execution or private receipt ownership |
| gate/rollback/backup-restore verification | `fleet` | evidence and landing control only |
| PropertyQuarry privacy lifecycle, intake, and user-visible closeout | repo `/docker/property`, package `app.api.routes`, module `app.api.routes.landing` | recorded by the verified PropertyQuarry decision; implementation remains blocked pending numeric product policy and independent re-review; Chummer and EA cannot act for it |
| PropertyQuarry minimization/redaction enforcement | dependency `public_tour_payloads` | enforces policy only; cannot change policy, authorize restoration, or close a case |
| PropertyQuarry revocation/deletion execution | dependency `property_tour_hosting` | executes only under `app.api.routes.landing` policy/authorization; cannot self-restore or close a case |

Every closeout receipt must record the applicable immutable-history expiry: 400 days from first manifest/tombstone creation for private or never-published records, or 548 days after public withdrawal/lease expiry.
Closeout does not restart either clock.

## Fail-closed rule

`TBD`, `null`, provider default, missing timestamps, indefinite retention, renewal by silence, or a provider's inability to delete fails policy.
The legal projection is `unverified` or `blocked`.

This policy is proposed canon for independent re-review only.
It does not accept the petition, authorize implementation or paid execution, establish provider readiness, publish mirrors, or widen public RUNSITE meaning.
