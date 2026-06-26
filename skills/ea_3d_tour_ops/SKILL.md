---
name: ea-3d-tour-ops
description: Use when any EA-backed product needs licensed 3D-tour tooling, 3DVista/Matterport/Pano2VR/krpano/MagicFit artifact intake, playable tour verification, redacted receipts, or operator handoff for tour exports across PropertyQuarry, Chummer runsite, or future product lanes.
---

# EA 3D Tour Ops

## Purpose

Use this internal EA operator skill when a product needs a playable 3D-tour artifact from a vendor tool or account-side export that cannot be produced safely by normal runtime automation.

This is not the customer-facing feature. Product runtimes still own public routes, entitlement checks, quota use, source refs, request receipts, and public-safe health. This skill owns operator/vendor work: licensed apps, export intake, verification, import staging, and redacted evidence.

## Product Adapters

Choose the adapter before doing work.

| Product | Runtime owns | Skill owns | Primary roots |
|---|---|---|---|
| `propertyquarry` | property records, tour URLs, branded `/tours` routes, property entitlements, property receipts | listing/provider export intake, hosted tour control verification, PropertyQuarry gold receipts | `/docker/property`, `/var/lib/docker/volumes/property_propertyquarry_public_tours/_data` |
| `chummer-runsite` | runsite packs, `HorizonCapability`, `HorizonArtifactRequest`, GM quota, Chummer-owned receipts, `/runsites/packs/{packId}/tour` | 3DVista/Matterport export intake, runsite tour URL proof, non-public vendor evidence | `/docker/chummercomplete/chummer.run-services`, product-owned runtime state |
| future product | product-owned routes, entitlements, receipts, source refs | vendor export intake and verifier receipts only | define before use |

## Rules

- First try configured APIs, local credentials, existing caches, and prepared import folders.
- Treat browser-only login, paid desktop export, Cloudflare challenge, physical media, or missing user file as an external artifact blocker.
- Send one concrete Telegram ask when the blocker cannot be solved autonomously.
- Never store raw passwords, bot tokens, license keys, private invoice signatures, reset links, session cookies, or private vendor URLs in tracked files.
- Store proprietary installers, vendor apps, and generated exports only in ignored runtime folders.
- Do not count ownership receipts, placeholder HTML, static screenshot galleries, or generated fallback pages as playable 3D-tour evidence.
- Every imported artifact needs a machine-readable receipt and verifier result.
- A paid license proves entitlement, not readiness. Readiness requires a playable hosted or exported tour that the product route can load.
- If a GUI tool is necessary, use Wine/Xvfb automation where reasonable, but stop before unsafe secret entry or destructive account-side changes.

## Accepted Evidence

- Matterport: verified hosted control route with safe manifest/private receipt.
- 3DVista: verified export containing provider runtime markers such as `tdvplayer.js`, or an allowlisted hosted 3DVista URL.
- Pano2VR: verified export containing runtime markers such as `pano2vr_player.js`, `pano.xml`, `gginfo.json`, `ggpkg`, or `ggskin`.
- krpano: real walkable scene/panorama/cubemap tour, not a plain image gallery.
- MagicFit: receipt-backed playable walkthrough media.

Reject placeholder HTML, static galleries, empty provider fields, license-only evidence, and public receipts that leak private vendor data.

## Standard Workflow

1. Identify product adapter, provider mode, subject/source ref, and expected public route.
2. Run the product verifier or existing release gate before asking for anything.
3. Read the missing provider mode from verifier output instead of guessing.
4. Discover candidate files in product-specific drop/cache folders, `/mnt/pcloud/EA`, and `~/Downloads`.
5. Cache installers under ignored vendor installer folders; stage complete exports under ignored incoming-tour folders.
6. Validate provider runtime markers before import.
7. Import/register the route using the product-owned runtime path.
8. Run the product verifier again and write a redacted receipt.
9. If still blocked, send an operator ask with exact missing file/export, safe link if available, target drop path, and reason.

## PropertyQuarry Adapter

Use this adapter for property search/review tours.

Standard paths:

- Repo: `/docker/property`
- User drop: `/mnt/pcloud/EA`
- Installer cache: `/docker/property/state/vendor_installers`
- Vendor apps: `/docker/property/state/vendor_apps`
- Incoming exports: `/docker/property/state/incoming_property_tours/<slug>/<provider>/`
- Public tour volume: `/var/lib/docker/volumes/property_propertyquarry_public_tours/_data`
- Receipts: `/docker/property/_completion/tours`

Commands from `/docker/property`:

```bash
python3 scripts/verify_property_tour_vendor_tooling.py \
  --write _completion/tours/property-tour-vendor-tooling-current.json

python3 scripts/verify_property_tour_controls.py \
  --tour-root /var/lib/docker/volumes/property_propertyquarry_public_tours/_data \
  --write _completion/tours/property-tour-controls-current.json

python3 scripts/propertyquarry_gold_status.py \
  --write _completion/propertyquarry-gold-status-current.json
```

Do not mark PropertyQuarry gold while `scripts/propertyquarry_gold_status.py` reports `blocked`.

## Chummer Runsite Adapter

Use this adapter for Chummer runsite 3D tours.

Runtime responsibilities:

- `HorizonCapabilityService` advertises `runsite-tour`.
- `HorizonArtifactRequestService` creates Chummer-owned receipts.
- `RunsiteTourQuotaService` enforces free/supporter weekly allowance.
- `RunsiteTour__Href`, `RunsiteTour__Label`, and `RunsiteTour__ActionLabel` configure hosted Matterport/3DVista tour dispatch.

Verification from `/docker/chummercomplete/chummer.run-services`:

```bash
dotnet test Chummer.Tests/Chummer.Tests.csproj \
  --filter "FullyQualifiedName~PublicLandingDownloadDispatchTests" --no-restore

BASE_URL=http://localhost:5099 \
EXPECT_RUNSITE_TOUR_HREF=https://3dvista.example.test/tour/abc \
EXPECT_RUNSITE_TOUR_LABEL='3DVista Tour' \
EXPECT_RUNSITE_TOUR_ACTION_LABEL='Launch 3DVista' \
  npx playwright test tests/public/runsite-public.spec.ts
```

Only use placeholder/example 3DVista URLs for local proof. Production receipts must point to product-owned public routes or redacted private receipts, not private vendor admin URLs.

## Operator Ask Template

```text
Please provide the complete <provider> export for <product>/<source-ref>.
Drop it at <target-folder>.
Required markers: <runtime marker list>.
Reason: the current verifier reports <missing-provider-mode>; ownership or screenshots are not enough because the public route must load a playable tour.
```
