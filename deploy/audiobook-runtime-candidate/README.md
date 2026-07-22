# Audiobook runtime candidate configuration

This directory contains an inert, configuration-only projection for reviewing a
four-service audiobook runtime candidate. It is not a deployment overlay, a
promotion handoff, a rollback mechanism, or an alternate production topology.

The live `ea-api` is memorial-owned. This candidate deliberately rejects a
memorial/candidate combination and records `owner_handoff_required` for the API.
It cannot become a production path unless the live owner approves either an
explicit handoff or a separately reviewed multi-mode contract that preserves the
memorial authority and mounts. Silent takeover is forbidden.

## Inert contract

The candidate file provides the following fail-closed controls:

- a fixed candidate-only Compose project and candidate-prefixed container names;
- one opt-in `audiobook-candidate-configuration-only` profile for every inherited
  service;
- zero replicas and restart disabled for every inherited service;
- exact immutable image references, `pull_policy: never`, and no build context for
  the four target services;
- exact command, entrypoint, working directory, user, capability, namespace,
  network, mount, and temporary-filesystem allowlists;
- exact rendered target-service field, environment-key, label-key, resource-limit,
  top-level volume, top-level network, and extension-definition allowlists;
- no source-code mounts, implicit host-path creation, Compose configs, Compose
  secrets, devices, or `volumes_from` attachments on the target services;
- denied deployment authority in both environment and labels.

Do not use this project with a command that creates or runs containers. The only
supported Compose operation is static `config` rendering.

## Read-only verification

Render the exact base, WhatsApp, and candidate inputs to JSON with the candidate
profile enabled:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.whatsapp-web-session.yml \
  -f deploy/audiobook-runtime-candidate/docker-compose.candidate.yml \
  --profile audiobook-candidate-configuration-only \
  config --format json > /private/preexisting/operator-directory/candidate.json
```

All required interpolation values must already be supplied by the operator's
private environment. The rendered JSON contains secrets and host paths and must
remain private.

Configuration verification performs no Docker runtime action:

```bash
python3 scripts/verify_audiobook_runtime_candidate.py \
  --mode configuration \
  --compose-json /private/preexisting/operator-directory/candidate.json \
  --expected-revision "$EA_AUDIOBOOK_CANDIDATE_REVISION" \
  --expected-image "$EA_AUDIOBOOK_CANDIDATE_IMAGE" \
  --receipt /private/preexisting/operator-directory/candidate-preflight.json
```

The verifier reads the Compose version, the clean Git commit containing the
overlay, and the exact overlay SHA-256. In `release` mode it additionally performs
a local, read-only `docker image inspect` and may validate an existing private
image-build receipt.
It never pulls an image. The currently available memorial image-build receipt is
supporting provenance only; it is not a signed, immutable audiobook candidate
authority.

Receipts contain a canonical digest of the full rendered contract. Environment
values, including secrets, are bound only inside the in-memory digest preimage;
they are never copied into the receipt. Validated bind sources and build contexts
are replaced with SHA-256 commitments before the outer contract hash is computed.
This binds the exact machine configuration without emitting a host path. A
configuration mismatch receives no valid rendered-contract digest.

The preflight receipt also contains a nested
`ea.audiobook_runtime_candidate_configuration.v1` projection for cross-lane
schema alignment. That projection is explicitly configuration-only,
non-authoritative, memorial-incompatible, owner-handoff-required, and ineligible
for group deployment. It must not be extracted or treated as deployment proof.
Any future group-deploy consumer must enforce those fields and remain blocked
until a separately reviewed memorial-compatible projection exists.

## Status and mandatory gates

A valid static projection returns `configuration_only`. Any mismatch, or any
attempt to use release mode without all evidence, returns `blocked`. Both statuses
always set deployment and promotion authority to false.

The following work remains outside this lane:

1. memorial owner handoff or an approved multi-mode API contract;
2. signed immutable generic candidate authority;
3. isolated candidate execution and runtime proof;
4. credentialed deployment and promotion authorization;
5. rollback capture and rehearsal;
6. live health, continuity, and postdeploy proof.

No deployment, recreation, promotion, rollback, live health mutation, or provider
action is implemented here.
