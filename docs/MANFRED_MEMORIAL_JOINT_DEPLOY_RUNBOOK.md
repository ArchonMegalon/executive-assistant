# Legacy joint API/ingress and PropertyQuarry compatibility reference

## Non-Memorial status

This is not the current Memorial release procedure. The current Memorial
surface is conversation-only and uses projection v4, runtime v6,
`make verify-manfred-memorial-promotion-preflight`, and
`make deploy-ea-memorial` through the scoped lane. It accepts no spatial
inputs and produces no spatial receipt.

The v5 joint/spatial semantics below are retained only as a quarantined,
separately tested PropertyQuarry compatibility plane. They cannot register a
current Memorial candidate, authorize a Memorial promotion, enter the Memorial
public receipt set, or block Memorial gold. Run their source-only compatibility
tests explicitly with:

```bash
make verify-propertyquarry-spatial-compatibility-source-gate
```

Do not execute the historical candidate/deploy commands below as a Memorial
operator procedure.

## Authority boundary

This is the only lane that may change both `ea-api` and `ea-cloudflared`. It is
not authorized while schema-v6 qualification is `enforced_soak`, resources are
unhealthy, any certification blocker remains, or the exact root-owned joint
permit body/commit marker/lock, trusted epoch-void ledger, or exact-epoch
`ea.vexp_qualification_certificate.v2` certificate pair is absent or
untrusted, or when a matching epoch-void entry exists. The v2 permit must bind the certificate's exact raw
SHA-256, canonical identity, schema, and qualification event hash. Never
manufacture the permit, relabel the API-only contract, invoke raw Compose, or
change sentinel, qualification, AppArmor, certificate, event-guard, or
mutation-gate state from this release lane. Missing or incompatible authority
plumbing is handled only by the separate commit-and-SHA-256-bound,
epoch-voiding recovery exception in `AGENTS.md`; that recovery cannot create or
resume joint promotion authority. The source-only request and verifier are
documented in `MANFRED_MEMORIAL_SCOPED_DEPLOY_RUNBOOK.md`; they remain blocked
until a Fleet-owned, signed, root-owned receipt binds both the durable
pre-change void evidence and the external exact-artifact manifest, and binds
the operator snapshot's claimed immutable epoch identity plus the independently
captured actual trusted sentinel-owned pre-change state SHA-256. The operator
snapshot is not live-state evidence and ordinary same-epoch sentinel rewrites
do not grant or revoke authority. A guarded-plumbing failure may restore only
artifacts from the sealed pre-change artifact manifest; the epoch void and
authority denial remain permanent.

Historical joint preflight required immutable root candidate finalization for
exact runtime-v5 and image-build-v3 receipt bytes. Those receipts are now
legacy/quarantined and are not selectable for Memorial promotion. A
passing candidate receipt, durable issuance alone, or an unsealed/aborted
candidate never satisfies this boundary.

The joint receipt has contract
`ea.memorial_joint_api_ingress_deploy.v1`. Its permit has contract
`ea.vexp_memorial_joint_mutation_permit.v2` and exactly these boundaries:

1. `before_ensure_redis`
2. `before_protect_previous_image`
3. `before_recreate_api`
4. `before_api_exec`
5. `before_api_interaction`
6. `before_rollback_api`
7. `before_recreate_cloudflared`
8. `before_rollback_cloudflared`
9. `before_rollback_network`

Rollback is recovery, but it is still a live mutation. Every rollback component
requires the current exact joint permit and coordination lock. If the permit is
missing, changed, or expired, rollback stops and the private journal is retained.
A replacement same-epoch permit is possible only while that exact epoch remains
terminal and unvoided. A voided epoch can never be reused: rollback must wait for
a strictly newer full seven-day epoch, its independently sealed certificate, and
a new exact-epoch permit from the governed root manager.

## Source proof

Source proof is safe to run without live authority and never creates a
candidate or contacts the public origin:

```bash
make verify-propertyquarry-spatial-compatibility-source-gate
```

Do not continue to candidate or deploy work until the hard authority boundary
above is satisfied.

## Historical v5 candidate and sealed spatial receipt (quarantined)

Follow `MANFRED_MEMORIAL_SCOPED_DEPLOY_RUNBOOK.md` to build and prepare the
isolated candidate. Give the governed runner both private output paths:

```bash
export EA_MEMORIAL_CANDIDATE_RECEIPT="$candidate_root/candidate-runtime.v5.json"
export EA_MEMORIAL_SPATIAL_BROWSER_RECEIPT="$candidate_root/candidate-browser.v5.json"
state_path="${VEXP_SENTINEL_STATE_PATH:?set the absolute schema-v6 state path}"
state_owner_uid="${VEXP_SENTINEL_STATE_OWNER_UID:?set its numeric owner uid}"

.venv/bin/python scripts/run_manfred_memorial_candidate.py \
  --env-file "$candidate_env" \
  --compose-file "$RELEASE_ROOT/deploy/manfred-memorial/docker-compose.candidate.yml" \
  --receipt "$EA_MEMORIAL_CANDIDATE_RECEIPT" \
  --spatial-browser-receipt "$EA_MEMORIAL_SPATIAL_BROWSER_RECEIPT" \
  --wait-seconds 240 \
  --vexp-state-path "$state_path" \
  --vexp-state-owner-uid "$state_owner_uid"
```

The standalone v5 file is an atomic, no-replace, private copy of the already
validated embedded browser gate. Joint preflight requires it to be absolute,
regular, current-EUID-owned, single-link, mode `0600`, status `pass`, and
exactly equal to the candidate v5 embedded object. It is revalidated before
every mutation boundary and before the final spatial handoff.

This runner requires the candidate-mode permit and its durable issuance record
from the scoped runbook. A passing v5 runtime receipt is not promotion authority.
While the exact permit that finalized it remains current, root must seal that
receipt and read-only verify the finalization against the bound v3 image-build
receipt:

```bash
manager=/usr/local/libexec/ea/manage-manfred-vexp-mutation-permit
candidate_permit_sha256="${VEXP_CANDIDATE_PERMIT_SHA256:?copy the exact successful candidate status permit_sha256}"
candidate_receipt_sha256="${EA_MEMORIAL_CANDIDATE_RECEIPT_SHA256:?copy the runtime receipt raw-byte SHA-256}"
image_build_receipt_sha256="${EA_MEMORIAL_IMAGE_BUILD_RECEIPT_SHA256:?copy the bound image-build receipt raw-byte SHA-256}"

/usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/python3 -I "$manager" seal-candidate \
  --state-path "$state_path" \
  --state-owner-uid "$state_owner_uid" \
  --candidate-receipt "$EA_MEMORIAL_CANDIDATE_RECEIPT" \
  --candidate-receipt-sha256 "$candidate_receipt_sha256"

/usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/python3 -I "$manager" candidate-seal-status \
  --candidate-permit-sha256 "$candidate_permit_sha256" \
  --candidate-receipt "$EA_MEMORIAL_CANDIDATE_RECEIPT" \
  --candidate-receipt-sha256 "$candidate_receipt_sha256" \
  --image-build-receipt-sha256 "$image_build_receipt_sha256"

/usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/python3 -I "$manager" revoke --permit-mode candidate
```

Continue only when `candidate-seal-status` returns contract
`ea.vexp_candidate_finalization.v1`, version `1`, and status `valid` at the fixed
root finalization path
`/var/lib/vexp-manfred-candidate-authority/finalizations/<candidate-permit-sha256>.json`.
The single fixed permit
path cannot hold candidate and joint contracts at the same time, and a candidate
permit is never promotion authority. An aborted candidate may be revoked without
a seal, but it can never enter joint preflight or promotion.

## Joint preflight

Prepare a clean durable release worktree with its upstream set to `origin/main`.
Set the same immutable image, candidate, projection, control-tour, and approved
HTTPS origin inputs used by the scoped component lane, then use a fresh
preflight deployment ID:

```bash
export EA_DEPLOYMENT_ID="manfred-preflight-$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}"
export EA_MEMORIAL_IMAGE="ea-runtime:manfred-$commit"
export EA_MEMORIAL_CONTROL_TOUR_SLUG="360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6"
export EA_PUBLIC_APP_BASE_URL="${MEMORIAL_PUBLIC_ORIGIN:?set the approved HTTPS origin}"

make verify-manfred-memorial-promotion-preflight
```

This performs source, API, Compose-input, ingress, network, public-edge,
rollback-renderability, candidate, and spatial checks without mutation. A
preflight receipt is single-use evidence; select a new deployment ID for the
actual promotion.

The API half is image-pure: the Memorial Compose override replaces inherited
base volumes and never overlays host source, scripts, configuration, or
release-evidence paths onto `/app`. Preflight requires runtime user
`10001:10001`, validates access to every remaining bind source, and seals a
redacted filesystem-identity snapshot. The joint lane revalidates that exact
snapshot inside `before_recreate_api` before it records API mutation possible;
permission, inode, mode, ACL, symlink, or metadata drift therefore stops before
either API or ingress recreation.

## Issue the exact joint permit

Install only the reviewed manager blob as root following the pinned install
procedure in the scoped runbook. From the reviewed root shell, issue and
immediately verify a short-lived joint permit against the exact terminal state.
The governed transaction reserves 900 seconds for forward work, 180 seconds
for rollback, and 30 seconds for transition, so admission requires more than
1110 seconds of remaining authority:

```bash
state_path="${VEXP_SENTINEL_STATE_PATH:?set the absolute schema-v6 state path}"
state_owner_uid="${VEXP_SENTINEL_STATE_OWNER_UID:?set its numeric owner uid}"
manager=/usr/local/libexec/ea/manage-manfred-vexp-mutation-permit

# Every manager issue/status mode and governed consumer requires this to be the
# designated non-root release operator's exact passwd-resolved
# .local/state/vexp-sentinel/state.json, selected by state_owner_uid; never a
# copied state or HOME-selected path.

# The candidate permit is already revoked, but its immutable finalization must
# still bind the exact runtime and image-build receipts selected for promotion.
/usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/python3 -I "$manager" candidate-seal-status \
  --candidate-permit-sha256 "$candidate_permit_sha256" \
  --candidate-receipt "$EA_MEMORIAL_CANDIDATE_RECEIPT" \
  --candidate-receipt-sha256 "$candidate_receipt_sha256" \
  --image-build-receipt-sha256 "$image_build_receipt_sha256"

# Both must be absent because the candidate permit was revoked.
/usr/bin/test ! -e /run/ea/memorial-vexp-mutation-permit.json
/usr/bin/test ! -e /run/ea/memorial-vexp-mutation-permit.commit.json

/usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/python3 -I "$manager" issue \
  --state-path "$state_path" \
  --state-owner-uid "$state_owner_uid" \
  --ttl-seconds 1800 \
  --permit-mode joint

/usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/python3 -I "$manager" status \
  --state-path "$state_path" \
  --state-owner-uid "$state_owner_uid" \
  --permit-mode joint
```

An API-mode permit is not interchangeable and must fail this lane.

## Joint promotion

Immediately after successful state-bound status, use a new deployment ID and
the governed Make target:

```bash
export EA_DEPLOYMENT_ID="manfred-$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}"
make deploy-ea-memorial-joint
```

The coordinator captures both baselines, proves the API locally, recreates and
proves ingress, verifies the exact credential-free public GET/HEAD surface, and
commits only after postdeploy release evidence succeeds. Any handled failure or
interruption after mutation enters joint rollback using the still-current joint
permit. If that authority is no longer current, rollback fails closed and the
recovery journal remains. Preserve the private receipt at:

```bash
export MEMORIAL_SPATIAL_DEPLOY_RECEIPT="$RELEASE_ROOT/.runtime/deployments/memorial/$EA_DEPLOYMENT_ID.json"
test "$(stat -c %a "$MEMORIAL_SPATIAL_DEPLOY_RECEIPT")" = 600
```

### Crash-recovery journal

After idempotent Redis-health preparation and prior-image tag protection, but
before either `ea-api` or `ea-cloudflared` can be recreated, the coordinator
durably records the rollback transaction at the deployment operator's
passwd-resolved home:

```text
~/.ea-memorial-deploy-state/joint-active-recovery.json
```

The location has no command-line or environment override. The operator is the
current EUID that owns the real `/docker/EA` directory; the state directory must
be a non-symlink, current-operator-owned directory with mode `0700`, and the
journal must be a regular, single-link, current-operator-owned file with mode
`0600`. If those invariants cannot be established, the lane fails before API
or ingress mutation. Redis start/health preparation and creation of the
protected image tag are intentionally outside the API+ingress rollback domain;
both are repeatable preparation side effects and are reported truthfully in the
deployment receipt.

Treat this journal as secret-bearing: it contains the exact private rollback
environment needed to restore the prior API and ingress after an uncatchable
process or host interruption. Never copy it into Git, a ticket, chat, Telegram,
or the public deployment receipt. Do not hand-edit, move, or delete it.

Every later joint invocation checks the canonical journal before preflight or
forward mutation. A preflight-only run reports recovery required and does not
mutate. Before a governed deploy can resume the recorded transaction, issue
and verify a fresh short-lived `--permit-mode joint` permit for the exact same
terminal epoch. The lane then revalidates that authority separately before the
ingress, API, and network rollback mutations while restoring the recorded
release paths, sealed rollback inputs, rendered Compose identity, protected
image, and Docker-daemon identity. It does not start a new promotion until
recovery has completed and the journal has been durably removed.

Successful commit or rollback must record the cleanup disposition and remove
the journal with a directory fsync. A retained journal or cleanup error is a
secret-bearing incident, not a successful completed launch. Preserve the
private transaction receipt and stop; do not retry with raw Compose or delete
the journal manually.

The committed receipt is launch evidence only when
`recovery_journal_cleanup.status` is exactly `removed`. A process or host crash
can occur in the narrow interval after the journal unlink is durable but before
that cleanup metadata is published. In that case the journal is already
absent, the committed receipt remains `pass` with `pending_after_commit`, and
the public spatial materializer intentionally blocks. Repair only that evidence
gap with the exact original deployment ID and receipt directory:

```bash
export EA_DEPLOYMENT_ID="${ORIGINAL_EA_DEPLOYMENT_ID:?set the exact committed ID}"
original_release_root="${ORIGINAL_RELEASE_ROOT:?set the original durable release root}"
.venv/bin/python scripts/deploy_ea_memorial_joint.py \
  --receipt-dir "$original_release_root/.runtime/deployments/memorial" \
  --finalize-committed-cleanup
```

The finalizer acquires the deployment locks, requires the canonical journal to
be securely absent, validates the private exact-ID receipt as an irrevocably
committed joint transaction, and atomically changes only the cleanup
disposition from `pending_after_commit` to `removed`. It cannot clear a
committed cleanup incident. It performs no Docker, Compose, network, provider,
or runtime mutation and requests no permit. It fails nonzero if the journal
exists, the receipt or directory is untrusted, or the commit cannot be proven.
Never use it to bypass a retained journal; a later governed joint invocation
must recognize and clean that committed transaction, then it updates the
original receipt to `removed` automatically.

Every `removed` cleanup record binds the canonical state directory's absolute
path, device, inode, owner UID/GID, mode, mtime, and ctime captured after the
journal unlink and directory fsync. The finalizer proves that exact identity
again after publishing the receipt and restores the prior pending receipt if
the proof fails. Do not move, replace, chmod, or reuse the state directory.

## Public launch evidence

Bind the exact candidate browser receipt and approved public origin, then run
the complete public gate. Supply the signed/manual room-review variables
required by `materialize-memorial-public-gold`; do not invent them for a
reviewer.

```bash
export MEMORIAL_SPATIAL_CANDIDATE_BROWSER_RECEIPT="$EA_MEMORIAL_SPATIAL_BROWSER_RECEIPT"
export MEMORIAL_PUBLIC_ORIGIN="$EA_PUBLIC_APP_BASE_URL"
export EA_PUBLIC_ORIGIN="$MEMORIAL_PUBLIC_ORIGIN"
export EA_SOURCE_REVISION="$commit"

make manfred-memorial-public-launch-gates
```

This sequence proves exact ingress GET/HEAD responses, materializes voice,
browser, meaningful-turn, room, and strict spatial receipts, verifies memorial
gold, and refreshes the operator projection. Candidate or local-only evidence
never substitutes for this public-origin proof. A joint receipt whose recovery
cleanup is missing, pending, or incident-retained is rejected even when its
transaction status is otherwise `pass`.

Previously generated spatial public-origin receipts backed by the historical
API-only deploy contract remain readable by the verifier for audit continuity.
They cannot authorize a new materialization. Every new spatial public-origin
receipt requires the joint API/ingress deploy contract and exact durable
`recovery_journal_cleanup.status=removed` evidence. The materializer securely
reopens the bound state directory with `O_DIRECTORY|O_NOFOLLOW`, requires its
exact recorded identity and trusted `0700` ownership, and proves the canonical
journal entry absent through that directory descriptor. A swapped directory,
changed metadata, or journal created after cleanup makes the old receipt
ineligible for new spatial gold.

## Revoke and incident boundary

Revoke the joint permit immediately after proof:

```bash
/usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/python3 -I "$manager" revoke --permit-mode joint
```

If rollback or recovery-journal cleanup reports a failure, preserve the private
receipt, both baselines, original release worktree, rollback tags, and journal
in place. Do not delete locks or the journal, hand-edit receipt status, or retry
through raw Docker. Treat unresolved API/ingress/network/public-edge identity
or a retained secret-bearing journal as an incident and inspect the exact
recorded component failure locally without disclosing environment values.

## External root evidence prerequisite

The mutable operator sentinel file cannot establish current health. The
external Fleet root owner must first install the reviewed
`/usr/local/libexec/vexp-current-predicate-attestor` and maintain the canonical,
root-owned `ea.vexp_current_predicate.v1` generation chain under
`/var/lib/vexp-qualification-current-predicate`. The atomic head must bind the
exact state bytes, epoch, certificate, boot ID, wall/monotonic sample, reviewed
sentinel producer, and reviewed root attestor. Any absent, stale, unchained, or
unreviewed evidence denies permit issue and joint deployment.

Candidate sealing also requires the external
`/usr/local/libexec/vexp-candidate-boundary-attestor` to append a nonce-bearing
root event for every exact builder/runtime mutation, then attest the exact
receipt bytes after no-replace publication under
`/var/lib/vexp-manfred-candidate-authority`. Its reviewed producer manifest pins
the exact builder and runner hashes. Expired monotonic publication deadlines
and root revocation records deny sealing. Append and revocation operations must
coordinate on the stable mutation lock.

This repository supplies only fail-closed consumers and a source-only Fleet
handoff request. It does not install either root producer. That handoff never
grants candidate, permit, merge, Docker, promotion, or live authority; recovery
must durably void the old epoch and a strictly newer seven-day schema-v6 epoch
must qualify through the normal root certificate and permit path.
