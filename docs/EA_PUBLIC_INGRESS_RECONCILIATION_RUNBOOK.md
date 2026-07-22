# EA public-ingress reconciliation

This is a read-only, fail-closed lane for the public `ea-cloudflared` path. It
shares `/run/lock/ea-memorial-ea-api.lock` with the scoped memorial deploy and
does not widen that deploy's API-and-Redis mutation contract.

## Hard boundary

The API-only component lane does not change cloudflared.
`scripts/reconcile_ea_public_ingress.py` rejects every standalone mutation
request with `public_ingress_reconciliation_coordinator_required`. Do not
relabel an API boundary, bypass the guard, or run the generated Compose topology
manually.

The only joint mutation lane is `scripts/deploy_ea_memorial_joint.py`. It
owns API/ingress/network/public-edge baselines in one rollback domain,
revalidates sealed evidence at `before_recreate_cloudflared`, and emits an
explicit joint receipt. Use `make verify-ea-memorial-joint-deploy` for its
non-mutating preflight and `make deploy-ea-memorial-joint` only after that
preflight passes. The standalone reconciliation lane remains read-only and
makes no container, network, Docker, or systemd change.

## Preflight

Use a new deployment ID for every run:

```bash
EA_DEPLOYMENT_ID=ingress-<revision>-<attempt> \
EA_SOURCE_REVISION=<exact-40-character-git-head> \
EA_PUBLIC_ORIGIN=https://myexternalbrain.com \
make verify-ea-public-ingress-preflight
```

The preflight requires a clean exact source revision, renders and validates the
source Compose files, checks the digest-pinned cloudflared image and security
posture, proves the stable `ea_public_ingress` subnet/gateway/IP and API trusted
proxy configuration, and captures the current cloudflared container, image,
Compose-input hashes, environment identity, command, security, and network
identity. The baseline and receipt are private mode `0600`; no environment value
or tunnel token is written.

If the API is not already on the exact stable network and revision, standalone
preflight returns `joint_api_ingress_coordinator_required`. That is an
intentional handoff to the reviewed joint preflight, never permission for the
standalone lane to mutate.

## Public proof after an authorized coordinated change

```bash
EA_DEPLOYMENT_ID=ingress-proof-<revision>-<attempt> \
EA_SOURCE_REVISION=<exact-40-character-deployed-revision> \
EA_PUBLIC_ORIGIN=https://myexternalbrain.com \
make verify-ea-public-ingress-public
```

This performs GET and HEAD checks for `/version`, the canonical memorial HTML
and manifest, and the spatial landing, manifest, and viewer. Every response must
be non-redirecting HTTP 200 with the expected media type and exact
`X-EA-Source-Revision`; `/version` must also report the same `commit_sha`.

The command is verification only. A passing public proof is not publication
authority and does not grant permission to mutate or remove any network.
