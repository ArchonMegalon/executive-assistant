# Manfred memorial scoped deploy runbook

## Scope notice

This is the current conversation-only Memorial contract. The public document
contains one main conversation surface with voice, text fallback, status,
retry, transcript, and audio controls. It contains no story/archive UI,
contribution UI, install upsell, conversation settings, personal-memory UI,
video avatar, memory-room navigation, PropertyQuarry tour, or 3D handoff.

The current source projection is
`ea.manfred_memorial_candidate_projection.v4`; the current runtime receipt is
`ea.manfred_memorial_candidate_runtime.v6`. Earlier projection/runtime
contracts remain readable only as legacy/quarantined evidence and cannot be
registered or promoted. `make deploy-ea-memorial` selects this scoped lane.
The joint API/ingress/PropertyQuarry lane is a separately tested legacy
compatibility plane; it is not a Memorial candidate, deploy, receipt-set, or
gold dependency.

## Hard stop before candidate or deploy work

Do not create a Manfred candidate image/runtime, run the memorial deploy lane,
or mutate the live ingress topology until the schema-v6 sentinel is terminal
`qualified`, the root finalizer has sealed
`ea.vexp_qualification_certificate.v2` for that exact epoch, and the fixed
root-installed manager has issued a current v2 permit bound to the exact raw
certificate SHA-256, canonical certificate identity, schema, and qualification
event hash. `enforced_soak`; a missing or untrusted state, certificate,
certificate sidecar, lock, permit body, durable permit commit marker, or
trusted epoch-void ledger; a matching epoch-void entry; unhealthy current
resources; or any certification blocker means deny. The certificate must be the root-owned
mode-`0640` pair at
`/var/lib/vexp-qualification-certificate/certificates/<epoch_ms>.json` and
`.json.sha256`; the sidecar is exactly `sha256:<raw-file-sha256>\n`.
Source-only preparation may continue, but none of the candidate or deployment
commands later in this runbook are authorized.

Missing or incompatible root authority plumbing is repaired only through the
separate epoch-voiding recovery exception in `AGENTS.md`. That recovery is not
part of this release lane, cannot create candidate or promotion authority, and
requires a strictly newer schema-v6 epoch plus a new full seven-day soak before
this runbook may continue.

The only governed order is:

1. finish the source-only conversation surface and voice/text routes;
2. prove terminal qualification and the exact root certificate, issue the
   first certificate-bound permit, and run state-bound `status` immediately
   before candidate creation;
3. build and verify the isolated runtime-v6 conversation candidate;
4. run non-mutating production preflight;
5. issue a fresh short-lived permit and run state-bound `status` immediately
   before promotion;
6. deploy only through `scripts/deploy_ea_memorial.py`;
7. prove the exact public conversation voice/text/browser/room surface; and
8. revoke the permit.

The installation, status, lease, and incident commands are pinned under
[Terminal qualification and root permit](#terminal-qualification-and-root-permit).

## Source-only qualification-plumbing recovery request

An explicit operator authorization to repair missing or incompatible schema-v6
qualification plumbing may be converted into a non-authoritative handoff
request. This is source preparation only. It does not void an epoch, install or
restart a unit, invoke Docker, create a candidate, issue a certificate or
permit, or authorize deployment.

Materialize only from an exact reviewed commit containing the tracked request
manifest and scripts. The authorization file is hashed but not copied into the
request; its reference must identify the explicit recovery instruction.
It must be a regular, single-link JSON file with contract
`ea.vexp_root_maintenance_operator_authorization.v1`, version `1`, scope
`schema_v6_qualification_plumbing_recovery`, the exact reviewed commit and
tracked manifest path, `source_request_only: true`,
`root_execution_authority: false`, and
`external_root_receipt_required: true`. Its `authorization_id` must equal the
CLI reference. This artifact authorizes preparation of the external handoff,
not root execution.

The materializer also requires a private operator-supplied schema-v6 state
snapshot. It reads that snapshot through a stable no-follow regular-file handle
and requires a current-operator-owned mode-`0600` file. The request binds the
snapshot's raw SHA-256 and size plus its claimed immutable epoch identity and
observed phase, floor, health, and predicate projection; it does not embed
blocker or deferment content. This snapshot has the explicit trust model
`untrusted_operator_supplied_snapshot` and does **not** establish live-state
truth. Successful local verification checks only request/source consistency and
never converts the snapshot into authority.

Known recovery defects such as a sub-seven-day observed floor or nullable
deferment/predicate fields are recorded as stable observation codes instead of
being relabeled as valid. They do not weaken the strict post-recovery contract.

The external root actor must independently perform a stable no-follow read of
the actual trusted sentinel-owned state, verify its configured owner, require
its immutable epoch identity to match the request, and atomically capture its
then-current raw SHA-256 in the durable void receipt immediately before the
first guarded change. Ordinary same-epoch sentinel rewrites therefore do not
stale the source request. An epoch-identity mismatch denies execution and
requires a new reviewed request; it must never be repaired by editing the
request or trusted state.

```bash
reviewed_commit="${EA_REVIEWED_EA_COMMIT:?set the exact reviewed 40-character commit}"
operator_authorization="${VEXP_RECOVERY_OPERATOR_AUTHORIZATION:?set the local authorization artifact}"
operator_state_snapshot="${VEXP_RECOVERY_OPERATOR_STATE_SNAPSHOT:?set the private operator state snapshot}"
request_dir="${VEXP_RECOVERY_REQUEST_DIR:?set a private mode-0700 directory}"
request="$request_dir/vexp-root-maintenance-recovery-request.v1.json"

python3 scripts/materialize_vexp_root_maintenance_recovery_request.py \
  --repo-root "$PWD" \
  --reviewed-commit "$reviewed_commit" \
  --operator-authorization "$operator_authorization" \
  --operator-authorization-reference "operator-approval/schema-v6-recovery" \
  --operator-state-snapshot "$operator_state_snapshot" \
  --output "$request"

python3 scripts/verify_vexp_root_maintenance_recovery_request.py \
  --repo-root "$PWD" \
  --request "$request"
```

Successful verification means only `valid_non_authoritative_request`; the
request itself remains `blocked_external_root_receipt_required` with every
authority flag false. It never grants root execution authority. EA cannot own
the compatible v2 certificate finalizer without violating its mirrored
implementation scope, so an independently governed Fleet lane must establish
its own pre-change authorization and later emit a signed, root-owned completion
receipt. That post-execution receipt must bind the operator snapshot's claimed
epoch identity, the atomically captured
actual pre-change state SHA-256, a durable pre-change epoch-void receipt, and
the exact reviewed root-artifact manifest before the first guarded change.
The source request cannot start that maintenance before or after the receipt;
without the receipt no downstream recovery-complete claim is allowed. Candidate
creation, merge, and live work remain denied throughout this recovery lane.

Before the void, the external actor must also seal a pre-change artifact
manifest for every guarded plumbing target. If a reviewed plumbing change
fails, only restoration of those manifest-bound pre-change plumbing artifacts
is allowed and the root receipt must record the disposition. The durable epoch
void remains permanent: rollback may not restore the voided epoch or any
certificate, permit, candidate, promotion, or live authority derived from it.

The fixed installed permit manager exposes `void-epoch` only for that external
reviewed recovery. It requires the root-owned mode-`0640` manifest at
`/var/lib/vexp-qualification-recovery/reviewed-maintenance-manifest.json`, with
the exact reviewed revision and artifact SHA-256 list. When the trusted
coordination lock exists, the transaction waits for it exclusively. If the lock
is absent, it first proves the permit body and commit are also absent, then
publishes the durable void without creating runtime plumbing. It atomically
creates the exact-epoch record
under `/var/lib/vexp-qualification-epoch-voids`, fsyncs it, and invalidates the
permit commit marker and body before returning. If the canonical ledger is
absent, this recovery-only transaction constructs a private sibling directory
whose first exact record and final metadata are already durable, then installs
the entire directory with atomic no-replace semantics. It never exposes an
empty canonical ledger. If the canonical ledger already exists, record
publication is also atomic no-replace and never uses a hard link. An exact
retry is idempotent; a conflicting record denies recovery and is never
overwritten. Its result always reports
`authority_granted: false`; it does not install artifacts, restart units, open
a new epoch, issue a certificate/permit, or authorize the caller to continue.
The external root executor must bind that result into its separately governed
completion receipt before the first manifest-listed plumbing change.

After any external repair, the sentinel must open a strictly newer schema-v6
epoch through its normal code path. Both wall-clock and monotonic qualification
duration must reach at least `604800000` milliseconds with healthy resources
and exactly empty blocker and deferment lists. Only the independent root
finalizer may then seal the exact-epoch v2 certificate; only afterward may the
separate root permit manager issue a certificate-bound v2 permit and stable
coordination lock. Neither this request nor the external recovery receipt is
release authority.

## Purpose

`make deploy-ea-memorial-scoped` is the current Memorial promotion lane.
It no longer invokes the inherited EA mega-stack deployer or the legacy joint
PropertyQuarry coordinator.
It may start `ea-redis`, but the only service it force-recreates is `ea-api`.

All runs take the fixed host-global lock
`/run/lock/ea-memorial-ea-api.lock` as well as a deployment-ID lock. Distinct
IDs and distinct release/receipt directories therefore cannot race the same
Compose project or API service.

The forward topology preserves the prior API's ordered Compose layers and adds
exactly one memorial override. Each captured config file must live below the
prior Compose working directory and have a corresponding path in the clean
release root. The lane rebases those relative paths into the release root, then
appends `docker-compose.memorial.yml`. A live base-only API therefore promotes
with base + memorial; a recorded base + production API promotes with base +
production + memorial. The lane rejects an already-present memorial override,
duplicate layer, or unmappable external layer before mutation.

If any API health, local memorial, public memorial, non-memorial compatibility,
evidence-refresh, or final gate check fails after the API change begins, the
lane restores the protected prior API image through the exact Compose project,
working directory, and config-file list recorded on the prior container. It
fails before mutation when that exact baseline cannot be resolved. The restore
itself uses `before_rollback_api` and therefore requires the same current
API-mode permit; if authority is no longer current, rollback fails closed and
the private failure receipt must be preserved for governed recovery.

## Release-root requirements

Deploy from a clean, durable release worktree on a branch with a configured
upstream. Do not deploy from a detached `HEAD`, the dirty development tree, or
an ephemeral `/tmp` directory. The lane enforces the attached branch, upstream,
and non-temporary root; these are not advisory checks. Application code is
owned by the immutable candidate image. The Memorial override deliberately
replaces the base volume list, so checkout files never shadow `/app` in the
non-root runtime.

The release root must contain:

- the committed memorial source and `memorial_data` candidate;
- a mode-`0600` production `.env`;
- the receipt-validated candidate release root exported as the absolute
  `EA_MEMORIAL_DATA_HOST_PATH`;
- the matching candidate runtime root exported as the absolute
  `EA_MEMORIAL_RUNTIME_HOST_PATH`;
- a writable private `.runtime` directory for deployment receipts.

Copy only the production environment without overwriting committed release
files. Memorial does not bind host `config/`, source, scripts, Dockerfiles,
requirements, or evidence directories into the API:

```bash
install -m 600 /docker/EA/.env "$RELEASE_ROOT/.env"
test ! -f /docker/EA/.env.local || install -m 600 /docker/EA/.env.local "$RELEASE_ROOT/.env.local"
mkdir -p "$RELEASE_ROOT/.runtime"
chmod 700 "$RELEASE_ROOT/.runtime"
```

Run `git status --short` after preparation. Ignored secrets may be present, but
the release-authority source projection must remain clean.

## Preflight

Choose a unique, explicit deployment identifier. Reusing an identifier is
rejected so a prior receipt cannot be overwritten.

Select a locally present candidate image whose tag contains the full 40-character
release revision, or use a repository SHA-256 digest. `latest`, short or unbound
tags, remote-only images, and unsafe image
references are rejected. The lane never builds or pulls this image; it resolves
the reference to a local immutable image ID before any mutation and later
requires the rendered override to retain the exact reference with
`pull_policy: never`, then requires the recreated API to use that exact ID.

Promotion also requires the private `0600` receipt from a passing isolated
candidate run. A regular, single-link, non-symlink receipt is mandatory; the
lane rejects older contracts. Runtime v6 binds the exact image ID and
source revision to the immutable memorial projection root/digest, isolated
Compose project and clean preflight, held project-name and candidate-port locks, provider-free
conversation/narrator/TTS/browser proof, live-EA before/after snapshots, candidate OpenAPI
counts/digests, and the exact candidate entry/mutation/finalization authority
envelope. Live OpenAPI comparison is explicitly deferred to governed promotion
and rollback; the candidate never claims it locally. The deploy receipt retains
only the candidate receipt path and hash plus bounded safe fields, never the
full snapshots.

Build, project, and prove the candidate before preflight. The candidate runner
leaves its isolated project running for soak and does not mutate the live `ea`
project:

```bash
cd "$RELEASE_ROOT"
umask 077

commit="$(git rev-parse HEAD)"
image="ea-runtime:manfred-$commit"
project_name="ea-manfred-candidate-${commit:0:12}"
candidate_root="$HOME/.local/share/ea-deploy/manfred-memorial/candidate-${commit}-18092"
export EA_MEMORIAL_IMAGE_BUILD_RECEIPT="$candidate_root/image-build.v3.json"
image_build_receipt="$EA_MEMORIAL_IMAGE_BUILD_RECEIPT"
public_origin="${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}"
state_path="${VEXP_SENTINEL_STATE_PATH:?set the absolute schema-v6 state path}"
state_owner_uid="${VEXP_SENTINEL_STATE_OWNER_UID:?set its numeric owner uid}"

mkdir -p "$candidate_root"
chmod 700 "$candidate_root"

.venv/bin/python scripts/build_manfred_memorial_image.py \
  --source-root "$RELEASE_ROOT" \
  --ref "$commit" \
  --tag "$image" \
  --receipt "$image_build_receipt" \
  --vexp-state-path "$state_path" \
  --vexp-state-owner-uid "$state_owner_uid"

.venv/bin/python scripts/prepare_manfred_memorial_candidate.py \
  --source-root "$RELEASE_ROOT" \
  --ref "$commit" \
  --image "$image" \
  --image-build-receipt "$image_build_receipt" \
  --deploy-root "$candidate_root" \
  --public-base-url "$public_origin" \
  --host-port 18092 \
  --project-name "$project_name" \
  --rotate-secrets \
  >"$candidate_root/prepare-output.v4.json"

candidate_env="$(jq -er '.env_file' "$candidate_root/prepare-output.v4.json")"
export EA_MEMORIAL_DATA_HOST_PATH
EA_MEMORIAL_DATA_HOST_PATH="$(jq -er '.release_root' "$candidate_root/prepare-output.v4.json")"
export EA_MEMORIAL_RUNTIME_HOST_PATH
EA_MEMORIAL_RUNTIME_HOST_PATH="$(jq -er '.runtime_root' "$candidate_root/prepare-output.v4.json")"
export EA_MEMORIAL_CANDIDATE_RECEIPT="$candidate_root/candidate-runtime.v6.json"

.venv/bin/python scripts/run_manfred_memorial_candidate.py \
  --env-file "$candidate_env" \
  --compose-file "$RELEASE_ROOT/deploy/manfred-memorial/docker-compose.candidate.yml" \
  --receipt "$EA_MEMORIAL_CANDIDATE_RECEIPT" \
  --wait-seconds 240 \
  --vexp-state-path "$state_path" \
  --vexp-state-owner-uid "$state_owner_uid"

test "$(stat -c %a "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = 600
test "$(jq -er '.schema' "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = \
  "ea.manfred_memorial_candidate_runtime.v6"
test "$(jq -er '.status' "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = "pass"
test "$(jq -er '.memorial_surface' "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = \
  "conversation_only"
test "$(jq -er '.spatial_scope' "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = \
  "separate_propertyquarry_lane"
test "$(jq -er '.public_property_tours_tested' "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = false
test "$(stat -c %a "$image_build_receipt")" = 600
test "$(jq -er '.schema' "$image_build_receipt")" = \
  "ea.manfred_memorial_image_build.v3"
test "$(jq -er '.status' "$image_build_receipt")" = "pass"
export EA_MEMORIAL_CANDIDATE_RECEIPT_SHA256
EA_MEMORIAL_CANDIDATE_RECEIPT_SHA256="$(sha256sum "$EA_MEMORIAL_CANDIDATE_RECEIPT" | cut -d ' ' -f 1)"
export EA_MEMORIAL_IMAGE_BUILD_RECEIPT_SHA256
EA_MEMORIAL_IMAGE_BUILD_RECEIPT_SHA256="$(sha256sum "$image_build_receipt" | cut -d ' ' -f 1)"
```

The governed image producer and candidate runner call the fixed installed
manager in isolated mode and require the exact candidate-mode permit. The image
producer revalidates it
while holding the root coordination lock across every Buildx create/build and
temporary image-verification runtime, cache prune, and candidate-image removal.
The candidate runner does the same across Compose `up`, container `exec`, API
`restart`, conversation/browser interaction, partial-project cleanup,
and receipt finalization while the shared lock remains held through no-replace
publication. Read-only inspection may occur between those boundaries. If
positive authority is lost, do not run raw Docker/Compose cleanup; leave the
bounded candidate resources for the exact governed
`ea-manfred-candidate-retention.timer` lane.

A passing runtime v6 receipt is still not promotion authority. While the exact
candidate permit that finalized it remains current, give the reviewed root shell
the absolute private runtime/image-build receipt paths and their raw-byte
SHA-256 values from the release operator. The root manager must seal the exact
runtime receipt against the durable candidate and image-build issuance records,
then the read-only status command must validate the same four operator inputs.
`candidate-seal-status` remains valid after revocation because it reads the
immutable root ledger; it does not make a candidate permit into an API or joint
permit.

```bash
manager=/usr/local/libexec/ea/manage-manfred-vexp-mutation-permit
candidate_receipt="${EA_MEMORIAL_CANDIDATE_RECEIPT:?copy the absolute passing v6 runtime receipt path}"
candidate_receipt_sha256="${EA_MEMORIAL_CANDIDATE_RECEIPT_SHA256:?copy its raw-byte SHA-256}"
image_build_receipt_sha256="${EA_MEMORIAL_IMAGE_BUILD_RECEIPT_SHA256:?copy the bound v3 image-build receipt SHA-256}"
candidate_permit_sha256="${VEXP_CANDIDATE_PERMIT_SHA256:?copy permit_sha256 from the successful candidate status}"

/usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/python3 -I "$manager" seal-candidate \
  --state-path "$state_path" \
  --state-owner-uid "$state_owner_uid" \
  --candidate-receipt "$candidate_receipt" \
  --candidate-receipt-sha256 "$candidate_receipt_sha256"

/usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/python3 -I "$manager" candidate-seal-status \
  --candidate-permit-sha256 "$candidate_permit_sha256" \
  --candidate-receipt "$candidate_receipt" \
  --candidate-receipt-sha256 "$candidate_receipt_sha256" \
  --image-build-receipt-sha256 "$image_build_receipt_sha256"

/usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/python3 -I "$manager" revoke \
  --permit-mode candidate
```

Only after `candidate-seal-status` returns contract
`ea.vexp_candidate_finalization.v1`, version `1`, and status `valid` may root
accept the immutable record at
`/var/lib/vexp-manfred-candidate-authority/finalizations/<candidate-permit-sha256>.json`,
revoke the candidate permit, and issue an API permit. If candidate work
aborts or never publishes a passing v6 receipt, root may revoke the unsealed
candidate permit to end its authority, but that candidate can never promote. A
revoked or expired candidate permit cannot be revived for late sealing; use a
fresh governed candidate invocation and new no-replace receipt paths.

```bash
cd "$RELEASE_ROOT"
commit="$(git rev-parse HEAD)"
export EA_DEPLOYMENT_ID="manfred-$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}"
export EA_MEMORIAL_IMAGE="ea-runtime:manfred-$commit"
test -n "${EA_MEMORIAL_CANDIDATE_RECEIPT:?run the isolated candidate first}"
test -n "${EA_MEMORIAL_DATA_HOST_PATH:?bind the proved projection root}"
test -n "${EA_MEMORIAL_RUNTIME_HOST_PATH:?bind the validated runtime root}"
export EA_PUBLIC_APP_BASE_URL="${MEMORIAL_PUBLIC_ORIGIN:?set the real HTTPS origin}"
docker image inspect "$EA_MEMORIAL_IMAGE" --format '{{.Id}}'
make verify-ea-memorial-scoped-deploy
```

The production origin must be HTTPS and its exact host must be approved. The
default allowlist is `myexternalbrain.com,www.myexternalbrain.com`. A different
production host requires an explicit comma-separated
`EA_MEMORIAL_PUBLIC_HOST_ALLOWLIST`; wildcards, paths, credentials, non-443
ports, and HTTP origins are rejected.

Preflight is fail-closed and performs no Docker mutation. It verifies:

- source-clean release authority bound to the requested deployment ID;
- declared `MEMORIAL` project mode and memorial deploy readiness;
- exact baseline-topology mapping into the release root plus memorial Compose
  resolution;
- an existing restorable `ea-api` baseline;
- a safe prior image reference, prior mount-identity digest, and locally
  resolved candidate image ID;
- an isolated render of the captured prior Compose root/layers that still
  reproduces the live API image reference/ID plus normalized environment,
  process (`Cmd`/`Entrypoint`/`User`), and mount-identity digests; `.env` drift
  therefore fails before forward mutation;
- a private passing runtime-v6 conversation-only candidate receipt bound to the exact v3
  image-build authority receipt, image, revision, memorial projection
  root/digest, isolated project/port, unchanged live EA snapshot, and
  provider-free browser proof, plus a valid immutable root finalization record
  returned by `candidate-seal-status` for those exact receipt bytes;
- a fresh preflight recomputation of the projection tree digest, file modes,
  file count, and byte count using the candidate producer's exact algorithm;
  receipt-only claims or a tree changed after candidate proof fail closed;
- explicit runtime user `10001:10001`, no supplemental groups, an image-pure
  `/app`, and exactly the sealed Memorial projection, three writable Memorial
  runtime roots, and artifacts volume;
- a no-follow bind-source access snapshot that models runtime UID/GID access,
  recursively seals the read-only projection without reading contents, and is
  revalidated inside the permit lease immediately before API recreation;
- attached release branch, configured upstream, and durable release root;
- a real configured public origin;
- an exact committed source revision;
- an exact clean source seal covering `HEAD`, the committed tree, the index
  tree, file modes, submodules, and tracked/untracked worktree status before
  and after every release-evidence subprocess;
- no-follow content and identity seals for forward and rollback Compose files,
  `.env`, and the optional `.env.local` presence/content, rechecked before and
  after evidence work and immediately before forward or rollback recreation;
- the live local OpenAPI sorted path set/count/digest; and
- explicit `memorial_surface=conversation_only` and
  `spatial_scope=separate_propertyquarry_lane`, with no tour mount, tour
  package, spatial receipt, or joint handoff consumed.

The preflight receipt is written privately under
`.runtime/deployments/memorial/<deployment-id>.json`. Because deployment IDs are
single-use, use a fresh ID for the actual deployment after a standalone
preflight.

Release context, manifest, authority, and operator projections are materialized
under a new `0700` per-deployment `predeploy/` evidence directory, never at
their tracked default paths. Each `0600` artifact is hash-bound into a private
phase manifest with the source tree, candidate image, projection digest, and
gate result. Any checkout mutation fails before the next evidence command.

## Deploy

```bash
cd "$RELEASE_ROOT"
commit="$(git rev-parse HEAD)"
export EA_DEPLOYMENT_ID="${EA_DEPLOYMENT_ID:-manfred-$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}}"
export EA_MEMORIAL_IMAGE="ea-runtime:manfred-$commit"
test -n "${EA_MEMORIAL_CANDIDATE_RECEIPT:?run the isolated candidate first}"
test -n "${EA_MEMORIAL_DATA_HOST_PATH:?bind the proved projection root}"
test -n "${EA_MEMORIAL_RUNTIME_HOST_PATH:?bind the validated runtime root}"
export EA_PUBLIC_APP_BASE_URL="${MEMORIAL_PUBLIC_ORIGIN:?set the real HTTPS origin}"
make deploy-ea-memorial-scoped
```

The lane performs these mutations only:

1. inspect `ea-redis`; leave it completely untouched when healthy, start the
   existing container directly when stopped, or use scoped
   `up -d --no-build --no-deps ea-redis` only when it is missing, followed by a
   required healthy inspection;
2. protect the current API image under an immutable deployment-specific local
   rollback tag;
3. `up -d --no-build --no-deps --force-recreate ea-api` with the memorial
   override and the explicitly selected candidate image.

It does not build, pull, stop, or recreate the database, workers, scheduler,
relay, Telegram services, WhatsApp services, proactive OODA, or Cloudflare
tunnel.

## Required proof

Success requires all of the following:

- the recreated `ea-api` is running, non-restarting, and Docker-healthy;
- its image ID equals the preflight-resolved candidate ID, its project/service
  labels are `ea`/`ea-api`, and its Compose working directory/config files are
  exactly the release topology;
- the running API recomputes the digest, file modes, file count, and byte count
  from its actual `/data/memorial_data` bind mount; any check/use swap or drift
  from the preflight projection triggers automatic rollback;
- `/app/app`, `/app/scripts`, and release evidence are image-owned and have no
  host bind overlays; the read-only `/data/memorial_data` mount resolves to the
  receipt-validated candidate release root;
- local `/health` returns `200`;
- local and public `/memorials/manfred` return the Manfred HTML surface;
- local and public `/memorials/manfred.json` return slug `manfred`;
- every local and public memorial HTML/JSON response carries
  `X-EA-Source-Revision` equal to the clean release commit;
- both projections state that the synthetic guide is not Manfred and does not
  speak for him;
- neither projection contains the first-person impersonation marker
  `Ich bin Manfred`;
- local and public memorial JSON bodies have the same SHA-256 digest;
- the full Manfred candidate verifier passes independently against local and
  public origins, including source-grounded narrator chat, TTS `409`, rendered
  browser checks, zero automatic provider work, zero WebSockets, zero failed
  requests/page errors, and zero same-origin HTTP 4xx/5xx responses;
- post-deploy OpenAPI retires exactly the two fixed governed-spatial POST
  operations, preserves every retained operation/schema/security scheme, and
  permits only the allowlisted compatible `GET /version` evolution;
- no PropertyQuarry tour route or 3D asset is mounted, requested, or treated
  as Memorial release evidence;
- a distinct private `postdeploy/` evidence set is rebuilt from scratch and
  refreshed release authority and memorial deploy readiness remain `pass`,
  with the exact predeploy public origin and authority posture unchanged.

Post-deploy evidence refresh remains inside the rollback-protected section. A
source-seal, evidence, or gate failure after API recreation restores the prior
API before the deploy can report `pass`.

The receipt stores statuses, response sizes and digests, the verified source
revision, image IDs, sanitized candidate-gate counters, mount-identity digests,
and rollback outcome. It never stores response bodies, arbitrary
request/response headers, raw mount identities, subprocess stdout/stderr,
environment values, or secrets.

## Automatic rollback

Any failure after the API change begins triggers one rollback attempt. The lane:

1. validates the captured prior image reference and retags the captured prior
   image ID to that exact reference;
2. resolves the exact `com.docker.compose.project.config_files` list from the
   prior container's recorded Compose working directory;
3. constructs a minimal rollback environment that excludes forward memorial,
   source-revision, image, deployment-mode, and Compose variables;
4. force-recreates only `ea-api` with `--no-build --no-deps`;
5. requires the restored image ID/reference, project/service identity, exact
  prior topology, prior mount-identity digest, one-way normalized environment
  and process-configuration digests (`Env`, `Cmd`, `Entrypoint`, `User`),
  healthy container, and local `/health`.

The baseline may legitimately be base-only or layered; the lane does not invent
an unrecorded production overlay during rollback. An unsuccessful rollback is
reported as `rollback_failed` and preserves both
the primary failure and rollback failure in the private receipt. Do not delete
the release worktree or rollback image tag until the rollout has been reviewed.

## Manual inspection

```bash
docker inspect -f '{{.State.Health.Status}} {{.Image}}' ea-api
curl -fsS -D - -o /dev/null https://myexternalbrain.com/memorials/manfred
curl -fsS -D - -o /dev/null https://myexternalbrain.com/memorials/manfred.json
python3 scripts/materialize_memorial_operator_status.py
python3 scripts/verify_release_authority.py --pretty
python3 scripts/verify_memorial_deploy_readiness.py --pretty
```

Do not claim memorial public-origin readiness unless both public routes and the
transparent-narrator contract pass at the configured production origin.

## Terminal qualification and root permit

The commands in this section distinguish the candidate contract from the
scoped Memorial API promotion contract. The legacy joint/PropertyQuarry permit
mode is outside the conversation-only Memorial release.

The candidate and promotion window is closed unless the schema-v6 sentinel is
terminal `qualified` and a short-lived root-owned permit proves that exact
epoch. `enforced_soak` is an unconditional deny. Missing state, lock, or permit
files; stale or malformed JSON; wrong ownership/mode; symlinks/hardlinks; an
unhealthy current resource set; or any certification blocker also deny. Do not
repair those conditions by editing sentinel state, hand-authoring permit JSON,
or invoking Docker directly. An explicitly authorized root-plumbing recovery
must follow the commit-and-SHA-256-bound, epoch-voiding exception in
`AGENTS.md`; its receipt never substitutes for terminal qualification,
certificate, permit, or lock evidence.

The permit manager uses the fixed permit body, durable commit marker, and lock:
`/run/ea/memorial-vexp-mutation-permit.json`,
`/run/ea/memorial-vexp-mutation-permit.commit.json`, and
`/run/ea/memorial-vexp-mutation-permit.lock`. It also requires the trusted
root-owned `/var/lib/vexp-qualification-epoch-voids` ledger and denies any
epoch with a matching entry. Candidate issue, status, sealing, and seal status
also require the fixed root-owned
`/var/lib/vexp-manfred-candidate-authority/{issuances,finalizations,operations,publications,revocations}`
ledger plus its reviewed `producer-manifest.json`.
The lock is a stable root-owned coordination
inode: the candidate/deploy lane holds a shared lease across each exact
mutation, while issue, revoke, and the recovery-only `void-epoch` transaction
take an exclusive lease. A permit lasts at most one hour and is revalidated at
every forward, cleanup, or rollback mutation boundary.

The ledger provisioning commands in the installation block below are only for
clean-host initialization before any schema-v6 qualification epoch is active.
Never run them to create, repair, replace, or relabel a missing/untrusted ledger
during `enforced_soak` or another active epoch. Normal `issue` and `status`
operations always fail closed when a required canonical ledger is absent. Only an
explicitly authorized, manifest-bound recovery may use `void-epoch`'s atomic
first-record bootstrap described above; the durable void is the first visible
canonical ledger state and grants no mutation authority.

Install the manager once per reviewed revision from a root shell. The Git
object is treated only as data: root does not import or execute Python from the
checkout. Replace all three required variables with review receipts before
running this block. `reviewed_commit` must be the exact 40-character commit ID,
not a branch or tag, and `reviewed_manager_sha256` must be the reviewed digest
of that commit's manager blob.

```bash
set -eu
umask 077
reviewed_repo="${EA_REVIEWED_EA_REPOSITORY:?set its absolute path}"
reviewed_commit="${EA_REVIEWED_EA_COMMIT:?set the reviewed 40-character commit ID}"
reviewed_manager_sha256="${EA_REVIEWED_PERMIT_MANAGER_SHA256:?set the reviewed blob SHA-256}"
stage_dir="$(/usr/bin/mktemp -d /root/ea-permit-manager.XXXXXX)"
trap '/usr/bin/rm -rf -- "$stage_dir"' EXIT HUP INT TERM
stage_file="$stage_dir/manage-manfred-vexp-mutation-permit"

materialized_commit="$(
  /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
    /usr/bin/git -c safe.directory="$reviewed_repo" -C "$reviewed_repo" \
    rev-parse --verify "$reviewed_commit^{commit}"
)"
/usr/bin/test "$materialized_commit" = "$reviewed_commit"
/usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/git -c safe.directory="$reviewed_repo" -C "$reviewed_repo" \
  cat-file blob "$reviewed_commit:scripts/manage_manfred_vexp_mutation_permit.py" \
  >"$stage_file"
/usr/bin/chmod 0400 "$stage_file"
materialized_sha256="$(/usr/bin/sha256sum "$stage_file" | /usr/bin/cut -d ' ' -f 1)"
/usr/bin/test "$materialized_sha256" = "$reviewed_manager_sha256"
/usr/bin/install -d -o root -g root -m 0755 /usr/local/libexec/ea
/usr/bin/install -o root -g root -m 0555 "$stage_file" \
  /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit
/usr/bin/install -d -o root -g 1000 -m 0750 \
  /var/lib/vexp-qualification-epoch-voids
/usr/bin/install -d -o root -g 1000 -m 0750 \
  /var/lib/vexp-manfred-candidate-authority \
  /var/lib/vexp-manfred-candidate-authority/issuances \
  /var/lib/vexp-manfred-candidate-authority/finalizations \
  /var/lib/vexp-manfred-candidate-authority/operations \
  /var/lib/vexp-manfred-candidate-authority/publications \
  /var/lib/vexp-manfred-candidate-authority/revocations
/usr/bin/test "$(/usr/bin/sha256sum \
  /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit | \
  /usr/bin/cut -d ' ' -f 1)" = "$reviewed_manager_sha256"
/usr/bin/test "$(/usr/bin/env -i LANG=C PATH=/usr/bin:/bin \
  /usr/bin/stat -c '%a:%u:%g:%h:%F' \
  /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit)" \
  = "555:0:0:1:regular file"
/usr/bin/test "$(/usr/bin/env -i LANG=C PATH=/usr/bin:/bin \
  /usr/bin/stat -c '%a:%u:%g:%F' \
  /var/lib/vexp-qualification-epoch-voids)" \
  = "750:0:1000:directory"
for candidate_authority_directory in \
  /var/lib/vexp-manfred-candidate-authority \
  /var/lib/vexp-manfred-candidate-authority/issuances \
  /var/lib/vexp-manfred-candidate-authority/finalizations \
  /var/lib/vexp-manfred-candidate-authority/operations \
  /var/lib/vexp-manfred-candidate-authority/publications \
  /var/lib/vexp-manfred-candidate-authority/revocations
do
  /usr/bin/test "$(/usr/bin/env -i LANG=C PATH=/usr/bin:/bin \
    /usr/bin/stat -c '%a:%u:%g:%F' "$candidate_authority_directory")" \
    = "750:0:1000:directory"
done
```

Do not replace the fixed installed file with a symlink or hardlink. Every
manager invocation below uses the fixed system interpreter in isolated mode
and an empty environment. The manager independently verifies those facts, its
fixed path, its exact mode and ownership, and its root-owned parent before it
reads or changes authority state.

Create `/var/lib/vexp-qualification-epoch-voids` with owner `root:1000` and mode
`0750` only during clean-host initialization before any schema-v6 epoch exists.
Never create an empty ledger during `enforced_soak`. Reviewed recovery with an
absent ledger uses `void-epoch`, whose first visible canonical directory already
contains the durable exact-epoch void record.

The fixed candidate-authority root and its `issuances/`, `finalizations/`,
`operations/`, `publications/`, and `revocations/`
subdirectories are likewise provisioned with owner `root:1000` and mode `0750`
only during reviewed installation or maintenance before an active qualification
epoch. Never create, repair, replace, chmod, or relabel them opportunistically
during `enforced_soak`. Candidate issuance and finalization records are
root-owned, group `1000`, mode `0640`, canonical JSON files published with
atomic no-replace semantics. Candidate-mode `issue` publishes the exact permit
issuance record before returning, and candidate-mode `status` requires that
exact issuance; a missing or untrusted ledger, issuance, or finalization is a
deny and is never repaired by the release operator.

Use this sequence:

1. Complete the source-only conversation surface and voice/text contracts
   without creating a candidate image/runtime.
2. After the sentinel becomes terminal, enter a reviewed root shell and issue
   the first exact-epoch **candidate-mode** permit. The state path and owner UID
   must be explicit. Every manager `issue`/`status` mode and every governed
   consumer accepts only the designated non-root release operator's
   passwd-resolved canonical `.local/state/vexp-sentinel/state.json`, selected by
   `state_owner_uid`, never a copied snapshot or `HOME` override. Run state-bound
   `status` immediately afterward; candidate image or
   runtime creation may start only after this exact command succeeds:

   ```bash
   state_path="${VEXP_SENTINEL_STATE_PATH:?set the absolute schema-v6 state path}"
   state_owner_uid="${VEXP_SENTINEL_STATE_OWNER_UID:?set its numeric owner uid}"
   manager=/usr/local/libexec/ea/manage-manfred-vexp-mutation-permit
   candidate_issue_json="$(
     /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
       /usr/bin/python3 -I "$manager" issue \
       --state-path "$state_path" \
       --state-owner-uid "$state_owner_uid" \
       --ttl-seconds 3600 \
       --permit-mode candidate
   )"
   /usr/bin/printf '%s\n' "$candidate_issue_json" | /usr/bin/python3 -I -c \
     'import json,sys; value=json.load(sys.stdin); assert value["status"] == "issued"; assert value["candidate_issuance"]["sha256"]'
   candidate_status_json="$(
     /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
       /usr/bin/python3 -I "$manager" status \
       --state-path "$state_path" \
       --state-owner-uid "$state_owner_uid" \
       --permit-mode candidate
   )"
   export VEXP_CANDIDATE_PERMIT_SHA256="$(
     /usr/bin/printf '%s\n' "$candidate_status_json" | /usr/bin/python3 -I -c \
       'import json,sys; value=json.load(sys.stdin); assert value["status"] == "valid"; print(value["permit_sha256"])'
   )"
   ```

3. Start the governed image builder immediately after that state-bound status,
   passing the same `--vexp-state-path` and `--vexp-state-owner-uid` values.
   Reissue and recheck a fresh candidate-mode permit if the build leaves too
   little validity for the runner, then pass the same values to the governed
   candidate runner and replace `VEXP_CANDIDATE_PERMIT_SHA256` with that new
   status result. The v3 image-build receipt keeps its own exact historical
   issuance binding; both issuances must have the same state owner/path, epoch,
   and certificate. While the authority is current, prove the exact image ID,
   source revision, projection digest, memorial routes, and priority 3D-tour
   HTML/JSON routes. Do not replace the governed candidate scripts with raw
   Docker commands.
4. While that exact candidate permit is still current, run `seal-candidate`
   followed by the read-only `candidate-seal-status` command shown above. Bind
   the exact absolute runtime-v5 receipt path, its raw-byte SHA-256, the
   image-build-v3 receipt SHA-256, and
   `VEXP_CANDIDATE_PERMIT_SHA256`. Continue only when status is `valid` for
   `ea.vexp_candidate_finalization.v1` version `1`.
5. Revoke the sealed candidate permit before changing contracts. An aborted
   candidate may also be revoked unsealed, but it cannot continue to this or any
   later promotion step:

   ```bash
   /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
     /usr/bin/python3 -I \
     /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit revoke \
     --permit-mode candidate
   ```

6. Run the non-mutating scoped production preflight:

   ```bash
   python3 scripts/deploy_ea_memorial.py --preflight-only
   ```

7. From the root shell, issue a fresh short-lived **API-mode** permit for the
   same state and run state-bound `status` again. The governed transaction
   reserves 900 seconds for forward work, 180 seconds for rollback, and 30
   seconds for transition, so admission requires more than 1110 seconds of
   remaining authority. Start deploy immediately after this succeeds:

   ```bash
   /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
     /usr/bin/python3 -I \
     /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit issue \
     --state-path "$state_path" \
     --state-owner-uid "$state_owner_uid" \
     --ttl-seconds 1800 \
     --permit-mode api
   /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
     /usr/bin/python3 -I \
     /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit status \
     --state-path "$state_path" \
     --state-owner-uid "$state_owner_uid" \
     --permit-mode api
   ```

8. In the release operator shell, deploy only through the scoped lane:

   ```bash
   python3 scripts/deploy_ea_memorial.py
   ```

9. Prove the exact deployed revision at the credential-free HTTPS origin,
   including `/memorials/manfred`, `/memorials/manfred.json`, and the configured
   priority `/tours/...` HTML and JSON. Preserve the private deployment/browser
   receipts.
10. Return to the root shell and revoke immediately:

   ```bash
   /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
     /usr/bin/python3 -I \
     /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit revoke \
     --permit-mode api
   ```

If revoke reports a busy lock, a governed mutation still owns the shared lease.
Wait for that action's 180-second deadline, inspect its receipt, then retry
revoke. If the lock remains busy because its holder was externally stopped or
is wedged, never delete or replace the stable lock. Use root process tooling to
identify the exact holder, capture its receipt and current container state, and
terminate only the governed deploy process tree under the incident procedure.
Verify API and rollback truth before retrying revoke. Do not stop, restart,
replace, or otherwise mutate sentinel or qualification units from this release
or incident lane. Separate root-plumbing recovery is governed only by the
epoch-voiding exception in `AGENTS.md` and cannot continue this deploy. A failed
or expired permit is a deny, not an invitation to bypass the lane.

## External root evidence prerequisite

The operator-owned sentinel state is diagnostic input, not current-health
authority. Before any new permit can be issued or consumed, the external Fleet
root owner must install the reviewed current-predicate attestor at
`/usr/local/libexec/vexp-current-predicate-attestor` and materialize the exact
root-owned `ea.vexp_current_predicate.v1` generation chain under
`/var/lib/vexp-qualification-current-predicate`. The atomic `current.json` head
must bind the exact state bytes, epoch, certificate, boot ID, wall and monotonic
sample, reviewed sentinel hash, and reviewed attestor hash. A missing manifest,
head, generation, predecessor, or producer binding is a deny.

Candidate sealing additionally requires the independently installed
`/usr/local/libexec/vexp-candidate-boundary-attestor` to append one root-owned,
nonce-bearing event for every exact candidate/image mutation and a
post-publication record under
`/var/lib/vexp-manfred-candidate-authority`. Its producer manifest must pin the
exact reviewed builder and candidate-runner hashes. Publication deadlines use
the same boot's monotonic clock; an expired publication or any corresponding
root revocation record denies sealing. The attestor must coordinate append and
revocation writes with the stable mutation lock.

EA contains only the fail-closed consumer contracts and the source-only Fleet
handoff request. It does not install or impersonate either root producer. The
reviewed recovery manifest grants no candidate, permit, merge, Docker,
promotion, or live authority; the old epoch must first be durably voided and a
strictly newer full seven-day epoch must qualify normally.
