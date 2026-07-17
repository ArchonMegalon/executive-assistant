# EA public-ingress reconciliation

This is a read-only, fail-closed lane for the public `ea-cloudflared` path. It
shares `/run/lock/ea-memorial-ea-api.lock` with the scoped memorial deploy and
does not widen that deploy's API-and-Redis mutation contract.

## Hard boundary

The current root-owned memorial mutation permit authorizes only the exact
API/Redis boundaries consumed by `scripts/deploy_ea_memorial.py`. It has no
cloudflared boundary. `scripts/reconcile_ea_public_ingress.py` therefore rejects
every standalone mutation request with
`public_ingress_reconciliation_coordinator_required`. Do not relabel an API
boundary, bypass the guard, or run the generated Compose topology manually.

A future coordinator must prove joint API-and-ingress rollback atomicity and
receive an exact root-issued ingress boundary before it can execute. Until then,
the reconciliation lane makes no container, network, Docker, systemd, sentinel,
qualification, certificate, AppArmor, event-guard, or mutation-gate change.

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

If the API is not already on the exact stable network and revision, preflight
returns `joint_api_ingress_coordinator_required`. That is an intentional stop:
the scoped memorial lane cannot safely deploy the API while a separate process
changes ingress, and neither lane may claim an atomic rollback it cannot prove.

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
