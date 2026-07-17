# Manfred memorial scoped deploy runbook

## Purpose

`make deploy-ea-memorial` is the governed public-memorial lane. It no longer
invokes the inherited EA mega-stack deployer. The lane may start `ea-redis`,
but the only service it force-recreates is `ea-api`.

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
fails before mutation when that exact baseline cannot be resolved.

## Release-root requirements

Deploy from a clean, durable release worktree on a branch with a configured
upstream. Do not deploy from a detached `HEAD`, the dirty development tree, or
an ephemeral `/tmp` directory. Compose bind mounts keep using the release root
for the lifetime of the container. The lane enforces the attached branch,
upstream, and non-temporary root; these are not advisory checks.

The release root must contain:

- the committed memorial source and `memorial_data` candidate;
- a mode-`0600` production `.env`;
- any ignored production configuration files required under `config/`;
- durable absolute host paths in `.env` for OneDrive, pocket audio, audiobook
  jobs, audiobook imports, and other state that must not resolve inside the
  release worktree;
- a writable private `.runtime` directory for deployment receipts.

Copy ignored configuration without overwriting committed release files:

```bash
install -m 600 /docker/EA/.env "$RELEASE_ROOT/.env"
test ! -f /docker/EA/.env.local || install -m 600 /docker/EA/.env.local "$RELEASE_ROOT/.env.local"
rsync -a --ignore-existing /docker/EA/config/ "$RELEASE_ROOT/config/"
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
lane rejects the older v2 and v3 contracts. Runtime v4 binds the exact image ID and
source revision to the immutable memorial projection root/digest, isolated
Compose project and clean preflight, held project-name and candidate-port locks, provider-free
narrator/TTS/browser proof, live-EA before/after snapshots, and OpenAPI
counts/digests. The deploy receipt retains only the candidate receipt path and
hash plus bounded safe fields, never the full snapshots.

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
public_origin="${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}"

spatial_bundle="${EA_MEMORIAL_SPATIAL_TOUR_BUNDLE_DIR:?set the pinned six-file tour bundle}"
spatial_authority="${EA_MEMORIAL_SPATIAL_AUTHORITY_RECEIPT:?set the publication-authority receipt}"
spatial_final_review="${EA_MEMORIAL_SPATIAL_FINAL_REVIEW_RECEIPT:?set the final-review receipt}"
spatial_browser_review="${EA_MEMORIAL_SPATIAL_BROWSER_REVIEW_RECEIPT:?set the exact-viewer browser receipt}"

mkdir -p "$candidate_root"
chmod 700 "$candidate_root"

.venv/bin/python scripts/build_manfred_memorial_image.py \
  --source-root "$RELEASE_ROOT" \
  --ref "$commit" \
  --tag "$image" \
  --receipt "$candidate_root/image-build.v2.json"

.venv/bin/python scripts/prepare_manfred_memorial_candidate.py \
  --source-root "$RELEASE_ROOT" \
  --ref "$commit" \
  --image "$image" \
  --deploy-root "$candidate_root" \
  --public-base-url "$public_origin" \
  --host-port 18092 \
  --project-name "$project_name" \
  --rotate-secrets \
  --spatial-tour-bundle-dir "$spatial_bundle" \
  --spatial-authority-receipt "$spatial_authority" \
  --spatial-final-review-receipt "$spatial_final_review" \
  --spatial-browser-review-receipt "$spatial_browser_review" \
  >"$candidate_root/prepare-output.v3.json"

candidate_env="$(jq -er '.env_file' "$candidate_root/prepare-output.v3.json")"
export EA_MEMORIAL_DATA_HOST_PATH
EA_MEMORIAL_DATA_HOST_PATH="$(jq -er '.release_root' "$candidate_root/prepare-output.v3.json")"
export EA_MEMORIAL_CANDIDATE_RECEIPT="$candidate_root/candidate-runtime.v4.json"

.venv/bin/python scripts/run_manfred_memorial_candidate.py \
  --env-file "$candidate_env" \
  --compose-file "$RELEASE_ROOT/deploy/manfred-memorial/docker-compose.candidate.yml" \
  --receipt "$EA_MEMORIAL_CANDIDATE_RECEIPT" \
  --wait-seconds 240

test "$(stat -c %a "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = 600
test "$(jq -er '.schema' "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = \
  "ea.manfred_memorial_candidate_runtime.v4"
test "$(jq -er '.status' "$EA_MEMORIAL_CANDIDATE_RECEIPT")" = "pass"
```

```bash
cd "$RELEASE_ROOT"
commit="$(git rev-parse HEAD)"
export EA_DEPLOYMENT_ID="manfred-$(date -u +%Y%m%dT%H%M%SZ)-${commit:0:12}"
export EA_MEMORIAL_IMAGE="ea-runtime:manfred-$commit"
test -n "${EA_MEMORIAL_CANDIDATE_RECEIPT:?run the isolated candidate first}"
test -n "${EA_MEMORIAL_DATA_HOST_PATH:?bind the proved projection root}"
export EA_MEMORIAL_CONTROL_TOUR_SLUG="360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6"
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
- a private passing runtime-v4 candidate receipt bound to the exact image,
  revision, memorial projection root/digest, isolated project/port, unchanged
  live EA snapshot, and provider-free browser proof;
- a fresh preflight recomputation of the projection tree digest, file modes,
  file count, and byte count using the candidate producer's exact algorithm;
  receipt-only claims or a tree changed after candidate proof fail closed;
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
- the required priority control-tour slug, with `200` HTML plus the exact JSON
  body digest captured for mandatory post-deploy equality.

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
export EA_MEMORIAL_CONTROL_TOUR_SLUG="360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6"
export EA_PUBLIC_APP_BASE_URL="${MEMORIAL_PUBLIC_ORIGIN:?set the real HTTPS origin}"
make deploy-ea-memorial
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
- read-only `/app/app`, `/app/scripts`, and `/data/memorial_data` mounts resolve
  to the clean release root;
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
- the required priority 3D control tour
  `360-tour-balkon-wohnung-in-neustift-layout-first-0146e6f9c6` still returns
  `200` for HTML and JSON, with the exact pre-deploy JSON digest unchanged;
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

The candidate and promotion window is closed unless the schema-v6 sentinel is
terminal `qualified` and a short-lived root-owned permit proves that exact
epoch. `enforced_soak` is an unconditional deny. Missing state, lock, or permit
files; stale or malformed JSON; wrong ownership/mode; symlinks/hardlinks; an
unhealthy current resource set; or any certification blocker also deny. Do not
repair those conditions by editing sentinel state, hand-authoring permit JSON,
or invoking Docker directly.

The permit manager uses the fixed files
`/run/ea/memorial-vexp-mutation-permit.json` and
`/run/ea/memorial-vexp-mutation-permit.lock`. The lock is a stable root-owned
coordination inode: the deploy lane holds a shared lease across each exact
mutation, while issue and revoke take an exclusive lease. A permit lasts at
most one hour and is revalidated at every mutation boundary.

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
/usr/bin/test "$(/usr/bin/sha256sum \
  /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit | \
  /usr/bin/cut -d ' ' -f 1)" = "$reviewed_manager_sha256"
/usr/bin/test "$(/usr/bin/env -i LANG=C PATH=/usr/bin:/bin \
  /usr/bin/stat -c '%a:%u:%g:%h:%F' \
  /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit)" \
  = "555:0:0:1:regular file"
```

Do not replace the fixed installed file with a symlink or hardlink. Every
manager invocation below uses the fixed system interpreter in isolated mode
and an empty environment. The manager independently verifies those facts, its
fixed path, its exact mode and ownership, and its root-owned parent before it
reads or changes authority state.

Use this sequence:

1. Complete source-only memorial and 3D-tour authority inputs without creating
   a candidate image/runtime.
2. After the sentinel becomes terminal, enter a reviewed root shell and issue
   the first exact-epoch permit. The state path and owner UID must be explicit.
   Run state-bound `status` immediately afterward; candidate creation may start
   only after this exact command succeeds:

   ```bash
   state_path="${VEXP_SENTINEL_STATE_PATH:?set the absolute schema-v6 state path}"
   state_owner_uid="${VEXP_SENTINEL_STATE_OWNER_UID:?set its numeric owner uid}"
   /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
     /usr/bin/python3 -I \
     /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit issue \
     --state-path "$state_path" \
     --state-owner-uid "$state_owner_uid" \
     --ttl-seconds 3600
   /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
     /usr/bin/python3 -I \
     /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit status \
     --state-path "$state_path" \
     --state-owner-uid "$state_owner_uid"
   ```

3. Start the governed candidate immediately after that state-bound status.
   While the authority is current, prove the exact image ID, source revision,
   projection digest, memorial routes, and priority 3D-tour HTML/JSON routes.
   Do not replace the governed candidate scripts with raw Docker commands.
4. Run the non-mutating scoped production preflight:

   ```bash
   python3 scripts/deploy_ea_memorial.py --preflight-only
   ```

5. From the root shell, issue a fresh short-lived permit for the same state and
   run state-bound `status` again. Start deploy immediately after this succeeds:

   ```bash
   /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
     /usr/bin/python3 -I \
     /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit issue \
     --state-path "$state_path" \
     --state-owner-uid "$state_owner_uid" \
     --ttl-seconds 900
   /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
     /usr/bin/python3 -I \
     /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit status \
     --state-path "$state_path" \
     --state-owner-uid "$state_owner_uid"
   ```

6. In the release operator shell, deploy only through the scoped lane:

   ```bash
   python3 scripts/deploy_ea_memorial.py
   ```

7. Prove the exact deployed revision at the credential-free HTTPS origin,
   including `/memorials/manfred`, `/memorials/manfred.json`, and the configured
   priority `/tours/...` HTML and JSON. Preserve the private deployment/browser
   receipts.
8. Return to the root shell and revoke immediately:

   ```bash
   /usr/bin/env -i HOME=/root LANG=C.UTF-8 PATH=/usr/bin:/bin \
     /usr/bin/python3 -I \
     /usr/local/libexec/ea/manage-manfred-vexp-mutation-permit revoke
   ```

If revoke reports a busy lock, a governed mutation still owns the shared lease.
Wait for that action's 180-second deadline, inspect its receipt, then retry
revoke. If the lock remains busy because its holder was externally stopped or
is wedged, never delete or replace the stable lock. Use root process tooling to
identify the exact holder, capture its receipt and current container state, and
terminate only the governed deploy process tree under the incident procedure.
Verify API and rollback truth before retrying revoke. Do not stop, restart,
replace, or otherwise mutate sentinel or qualification units. A failed or
expired permit is a deny, not an invitation to bypass the lane.
