# Governed audiobook production preparation

This directory defines the smallest production-shaped audiobook handoff that is
safe before runtime activation. The checked-in overlay describes three paused
services at zero replicas with an exact idle command. It cannot consume a queue,
call a provider, publish an artifact, send a message, build, pull, or mutate the
memorial-owned `ea-api`.

The verifier is preparation-only. A successful run returns `status=prepared`
and a digest-bound projection for a separate governed consumer. It always keeps
all deploy, stage-mutation, activation, queue, provider, send, build, and pull
authority false. It has no authorize mode.

## Exact source and memorial baseline

The preparation binds this exact committed Compose inventory, in order:

1. `docker-compose.yml`
2. `docker-compose.memorial.yml`
3. `docker-compose.whatsapp-web-session.yml`
4. `deploy/audiobook-runtime-production/docker-compose.production-stage.yml`

The verifier reads each file without following any path-component symlink and
compares its SHA-256 to the exact Git blob at the expected 40-character commit.
Git runs through a validated root-owned executable with a fixed environment:
inherited `GIT_*` controls and user/system configuration are absent, replacement
objects are disabled and rejected, lazy fetching and every transport protocol
are disabled, credential and SSH prompts fail closed, object alternates are
rejected, and the real worktree, Git directory, common directory, and `HEAD`
identities are bound. A missing committed object is therefore a hard failure,
not permission to contact a promisor remote or execute its upload-pack helper.
The verifier repeats clean-worktree, committed-blob, and working-file checks
before materializing a receipt, so an overlay digest cannot be attached to
mutable bytes from another revision.

The baseline render must use the first three files with project name `ea`. Its
entire canonical render and canonical `ea-api` definition must match a current,
root-owned `ea.memorial_runtime_baseline.v1` receipt. The staged render adds only
the fourth file. It must preserve the exact service inventory, every non-stage
service, all top-level networks, the exact pruning of the now-unused
`ea_whatsapp_web_actions` volume definition, and the memorial API. The three
stage services use exact document keysets, environment and label allowlists,
resource bounds, zero replicas, no ports or mounts, and one exact idle command.

## Evidence contracts

Preparation requires:

- a current root-owned memorial baseline receipt with an exact Compose source
  inventory, baseline render digest, and API digest;
- an exact `ea.audiobook_runtime_image_provenance.v1` document binding source
  revision, immutable image reference, local image ID, and SBOM digest;
- an exact `ea.audiobook_runtime_image_sbom.v1` envelope whose CycloneDX root
  component binds the same source revision, image reference, image ID, document
  namespace, and serial number.

All private rendered Compose and evidence JSON inputs must be regular,
single-link, operator-owned files with mode `0600`. The memorial baseline and
must be a regular, single-link, UID-0-owned file with mode `0644`. Root authority
traversal first validates `/` itself as the same UID-0, non-writable directory
seen through both descriptor and path metadata, then validates every descendant
without following symlinks. Root ownership is fixed in code and cannot be
supplied by a CLI argument.

## Preparation

Render the baseline from base + memorial + WhatsApp, then render the stage by
adding the production-stage overlay. Store both JSON files in an already-created
operator-private directory and run:

```bash
python3 scripts/verify_audiobook_runtime_production_stage.py \
  --baseline-compose-json /private/operator/baseline.json \
  --staged-compose-json /private/operator/staged.json \
  --expected-revision "$SOURCE_REVISION" \
  --expected-image "$IMMUTABLE_IMAGE" \
  --expected-image-id "$IMAGE_ID" \
  --compose-version "$COMPOSE_VERSION" \
  --memorial-baseline-receipt /run/ea/memorial-runtime-baseline.json \
  --provenance /private/operator/provenance.json \
  --sbom /private/operator/sbom.json \
  --receipt /private/operator/production-stage-prepared.json
```

A prepared receipt is not a bearer grant. It exposes only immutable digests and
the `stage_projection_sha256` needed by the governed consumer. Policy-free
preparation uses `ea.audiobook_runtime_production_preflight.v2` with an embedded
`ea.audiobook_runtime_production_projection.v2`; the governed consumer emits
`ea.audiobook_runtime_governed_deploy.v2`. The checked-in paused-stage overlay
remains `ea.audiobook_runtime_production_stage_overlay.v1` because its exact
shape did not change.

## Governed mutation boundary

The deployment consumer validates the exact prepared projection, target render,
pre-state, rollback plan, source/image/evidence summaries, and memorial baseline.
It rechecks immutable evidence and live state before mutation, uses no build or
pull path, creates only the stopped worker stage, verifies memorial controls, and
rolls back the exact worker pre-state on failure.

Runtime activation remains a separate, absent authority plane. It requires a
distinct activation overlay and explicit approval plus runtime-enforced queue,
provider, credit, transport, recipient, send, expiry, revocation, rollback, and
post-activation controls. Nothing in this preparation contract can grant it.
