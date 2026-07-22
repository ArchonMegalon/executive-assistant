# Manfred memorial joint API and ingress deploy

## Deployment boundary

This is the only lane that may change both `ea-api` and `ea-cloudflared`. It is
available only after the source gate, isolated candidate and sealed spatial
receipt, and non-mutating joint preflight pass for the exact release revision.
Never relabel the API-only contract, invoke raw Compose, or bypass the joint
coordinator's baseline, rollback, and public-origin checks.

The current operator EUID, its private bundle parent, and the selected Docker
transport are the execution trust boundary. Do not run concurrent same-EUID
filesystem or Docker mutations during preflight, normalization, recovery, or
promotion; possession of that account and Docker transport already grants the
ability to replace the governed inputs or mutate the runtime directly.

The joint receipt has contract
`ea.memorial_joint_api_ingress_deploy.v2`. The coordinator revalidates sealed
evidence at exactly these forward-mutation boundaries:

1. `before_ensure_redis`
2. `before_protect_previous_image`
3. `before_recreate_api`
4. `before_recreate_cloudflared`

Rollback is journal-driven recovery and cannot start a different promotion.

## Source proof

Source proof is safe to run without live authority and never creates a
candidate or contacts the public origin:

```bash
make verify-manfred-memorial-source-gate
```

Continue to candidate work only after this source proof passes.

## Candidate and sealed spatial receipt

Follow `MANFRED_MEMORIAL_SCOPED_DEPLOY_RUNBOOK.md` to build and prepare the
isolated candidate. Give the governed runner both private output paths:

```bash
export EA_MEMORIAL_CANDIDATE_RECEIPT="$candidate_root/candidate-runtime.v5.json"
export EA_MEMORIAL_SPATIAL_BROWSER_RECEIPT="$candidate_root/candidate-browser.v5.json"

.venv/bin/python scripts/run_manfred_memorial_candidate.py \
  --env-file "$candidate_env" \
  --compose-file "$RELEASE_ROOT/deploy/manfred-memorial/docker-compose.candidate.yml" \
  --receipt "$EA_MEMORIAL_CANDIDATE_RECEIPT" \
  --spatial-browser-receipt "$EA_MEMORIAL_SPATIAL_BROWSER_RECEIPT" \
  --wait-seconds 240
```

The standalone v5 file is an atomic, no-replace, private copy of the already
validated embedded browser gate. Joint preflight requires it to be absolute,
regular, current-EUID-owned, single-link, mode `0600`, status `pass`, and
exactly equal to the candidate v5 embedded object. It is revalidated before
every mutation boundary and before the final spatial handoff.

## Split-label API baseline normalization

If the live API's Compose labels name a working directory without `.env` and
ordered Compose files below a different root, normal preflight must continue to
reject that baseline. Do not copy files into the recorded directory, use the
mutable external checkout, invoke raw Compose, or relax the external-layer
check.

The following target writes only a private, non-authoritative recovery plan. It
does not inspect or mutate Docker, invoke Compose or Git, contact HTTP origins,
read environment/config contents, cross a mutation boundary, or write the
canonical recovery journal. Every live, image, Git, security, network, ingress, and public
identity assertion remains `required_unverified`; the plan has no promotion or
mutation authority and cannot be used as candidate, spatial, deploy, or public
launch evidence.

```bash
export EA_BASELINE_PLAN_ID="api-baseline-plan-$(date -u +%Y%m%dT%H%M%SZ)"
export EA_BASELINE_RECORDED_WORKING_DIR="${EXACT_LABEL_WORKING_DIR:?set the audited absolute path}"
export EA_BASELINE_EXTERNAL_CONFIG_ROOT="${EXACT_LABEL_CONFIG_ROOT:?set the audited absolute path}"
export EA_BASELINE_TRUSTED_ENVIRONMENT_ROOT="${EXACT_TRUSTED_ENV_ROOT:?set the audited absolute path}"
export EA_BASELINE_EXPECTED_REVISION="${EXACT_LIVE_SOURCE_REVISION:?set the audited 40-character revision}"
export EA_BASELINE_EXPECTED_IMAGE_REFERENCE="${EXACT_LIVE_IMAGE_REFERENCE:?set the audited tagged reference}"
export EA_BASELINE_EXPECTED_IMAGE_ID="${EXACT_LIVE_IMAGE_ID:?set the audited sha256 image ID}"
export EA_BASELINE_PLAN_OUTPUT="$RELEASE_ROOT/.runtime/api-baseline-normalization-plan.json"

make plan-ea-memorial-api-baseline-normalization
```

The output parent must already be a non-symlink, current-operator-owned
mode-`0700` directory. The mode-`0600` plan is created with no-replace
semantics. The plan deliberately remains non-authoritative even when consumed
by the separately reviewed normalizer.

The current exact-shape contracts are normalization plan v2, operation receipt
v2, preflight receipt v2, and terminal receipt v2. Their v1 forms are
retired and rejected; do not relabel or extend a v1 artifact to make it look
like v2. Generate fresh v2 evidence with the commands in this section.

Create a fresh private mode-`0700` bundle parent, select a fresh operation ID,
and run the normalizer's read-only preflight first:

```bash
export EA_DEPLOYMENT_ID="api-baseline-preflight-$(date -u +%Y%m%dT%H%M%SZ)"
export EA_BASELINE_PLAN_INPUT="$RELEASE_ROOT/.runtime/api-baseline-normalization-plan.json"
export EA_BASELINE_BUNDLE_PARENT="$RELEASE_ROOT/.runtime/api-baseline-bundles"
export EA_PUBLIC_ORIGIN="${MEMORIAL_PUBLIC_ORIGIN:?set the approved HTTPS origin}"

make verify-ea-memorial-api-baseline-normalization
```

Preflight requires clean current `main`, exact agreement among the plan, live
container, immutable image, and Git source revision, and an exact reconstruction
of the live API Compose hash. It creates a private sealed, tamper-evident
Git-object/config/environment bundle. Bundle v3 reserves exactly five render
inputs reconstructed from the already-validated live API: its immutable image,
source revision, read-only Memorial data bind root, writable Memorial runtime
bind root, and trusted proxy CIDRs. Those values are appended to the bundle's
private mode-`0600` `.env.local`, covered by the manifest and recovery seal, and
never accepted from the caller environment. The two public source bindings
(image reference and revision) remain in receipts and the recovery journal as
required evidence; the two private host roots and proxy CIDRs do not. Any
same-named entry in the trusted environment is an ambiguity and fails closed.
For dotenv-only settings, v3 also derives a value-free environment-name
inventory from the live API before and after rendering. The retained private
environment files remain complete, but the canonical normalization override
projects only trusted names already present in that stable live inventory.
Newly inventoried disabled settings therefore cannot change the normalization
baseline. The selected count and name-set digest are sealed in the manifest;
the exact live Compose-hash equality gate proves the selected values without
putting names or values into public receipts. Recovery replays that sealed
canonical subset and never consults the then-current live inventory.
The preflight also captures the API, cloudflared, Docker daemon, public-network,
and twice-stable 12-probe public identities, and writes an operational preflight
receipt. It does not create the recovery journal, protect or retag an image,
cross a mutation boundary, or invoke `compose up`.

Bundle v1 is deliberately not recovery-compatible: it did not guarantee these
five render values were retained and therefore cannot prove a caller-free
restart after API mutation. Bundle v2 projected every eligible trusted
dotenv-only name and cannot preserve an older live baseline after new disabled
settings are inventoried. Upgrade only while the canonical normalization
journal is securely absent, retain old bundles for audit, and create the
distinct immutable v3 bundle. Never relabel or rewrite a v1/v2 artifact as v3.

After the read-only preflight passes, use a new operation ID and run:

```bash
export EA_DEPLOYMENT_ID="api-baseline-normalize-$(date -u +%Y%m%dT%H%M%SZ)"
make execute-ea-memorial-api-baseline-normalization
```

Under the global API mutation lock, the executor revalidates all preflight
evidence, proves that joint recovery is absent, and durably creates its distinct
normalization journal before image protection. It records each possible
mutation before crossing it. Its sole service mutation is the sealed bundle's
exact `docker compose ... up -d --no-build --no-deps --pull never
--force-recreate ea-api`.
It does not start or change Redis, build or pull an image, issue a network
create/remove/reconfigure command, or invoke the ingress lane. API recreation
necessarily replaces that service's endpoint; commit therefore requires final
public-network semantic equality along with the same Docker daemon, immutable
API runtime domains, cloudflared runtime, Compose hash, and twice-stable public
edge. Only the three API Compose topology labels may change, and they must name
the retained bundle.

The exact terminal receipt is a private mode-`0600` no-replace file directly
under `$RELEASE_ROOT/.runtime`, bound to the journal's transaction ID and
separate from the evolving operational receipt. A durable commit retains both
the sealed bundle and the protected prior-image tag. Neither receipt grants
candidate, spatial, promotion, deploy, or public-launch authority.

Crash recovery is journal-driven. On a later non-preflight
invocation using a fresh operation ID, the executor reads the canonical journal
before consulting the current plan, checkout, environment files, or
caller-supplied public origin; the journal retains the interrupted transaction's
terminal-receipt path:

| Durable state | Required recovery |
| --- | --- |
| `prepared` | Prove the complete baseline and absent protected tag, write `clean_abort`, then remove the journal. |
| `protect_previous_image_possible` before API authorization | Prove any tag is the recorded image, remove only that exact tag, prove the complete baseline, write `verified_recovery`, then remove the journal. |
| `rollback_failed` with API authorization still false | Retry the protect-only recovery path, prove the complete baseline, and finish as `verified_recovery`. |
| `api_mutation_possible`, or `rollback_failed` with API authorization true | Prove the daemon, protected image, cloudflared, and unaffected network/runtime domains; reuse the retained sealed bundle to complete the target API topology; write `verified_forward_recovery`; retain the protected tag. |
| `commit_pending` | Revalidate the exact terminal receipt and current terminal identities, then complete journal removal idempotently. |
| `cleanup_pending` | Revalidate the already-bound exact terminal receipt and complete the interrupted journal removal without another mutation. |
| Missing, malformed, or untrusted canonical state | Stop with that state byte-for-byte untouched and perform no mutation. |
| Mismatched recovery evidence after a valid attempt starts | Retain the canonical state, durably mark `rollback_failed` when allowed, and make no further tag, API, ingress, or network change after detecting the mismatch. |

After normalization, regenerate source-bound candidate and spatial evidence at
the then-current `main`, rerun normal joint preflight, and use the normal
promotion lane below. Normalization makes the old API baseline safely
renderable; it never substitutes for promotion.

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

## Joint promotion

After the joint preflight passes, use a new deployment ID and the governed Make
target:

```bash
export EA_DEPLOYMENT_ID="manfred-$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}"
make deploy-ea-memorial
```

The coordinator captures both baselines, proves the API locally, recreates and
proves ingress, verifies the exact credential-free public GET/HEAD surface, and
commits only after postdeploy release evidence succeeds. Any handled failure or
interruption after mutation enters joint rollback without requesting new
promotion inputs. Preserve the private receipt at:

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
mutate. A governed deploy resumes the recorded transaction from its original
release paths, sealed rollback inputs, rendered Compose identity, protected
image, and Docker-daemon identity without accepting new promotion inputs. It
does not start a new promotion until recovery has completed and the journal has
been durably removed.

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
or runtime mutation. It fails nonzero if the journal
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

## Incident boundary

If rollback or recovery-journal cleanup reports a failure, preserve the private
receipt, both baselines, original release worktree, rollback tags, and journal
in place. Do not delete locks or the journal, hand-edit receipt status, or retry
through raw Docker. Treat unresolved API/ingress/network/public-edge identity
or a retained secret-bearing journal as an incident and inspect the exact
recorded component failure locally without disclosing environment values.
