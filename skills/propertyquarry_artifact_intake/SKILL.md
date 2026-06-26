---
name: propertyquarry-artifact-intake
description: Use for PropertyQuarry-specific 3D-tour artifact intake, vendor export staging, playable tour verification, and redacted release receipts; delegates shared Matterport/3DVista/Pano2VR/krpano/MagicFit operator workflow to ea-3d-tour-ops.
---

# PropertyQuarry Tour Ops

Use the shared EA tour skill first:

`/docker/EA/skills/ea_3d_tour_ops/SKILL.md`

This file remains as the PropertyQuarry-specific adapter name for existing references. It applies when PropertyQuarry needs licensed 3D-tour tooling, vendor exports, operator artifact intake, playable tour verification, or release-gate receipts.

## PropertyQuarry Defaults

- Product adapter: `propertyquarry`
- Repo: `/docker/property`
- User drop: `/mnt/pcloud/EA`
- Installer cache: `/docker/property/state/vendor_installers`
- Vendor apps: `/docker/property/state/vendor_apps`
- Incoming exports: `/docker/property/state/incoming_property_tours/<slug>/<provider>/`
- Public tour volume: `/var/lib/docker/volumes/property_propertyquarry_public_tours/_data`
- Receipts: `/docker/property/_completion/tours`

## Required Boundary

The skill is not a product feature. PropertyQuarry owns customer-facing property records, branded tour URLs, entitlements, public routes, and receipts. EA tour ops only stages, imports, verifies, and receipts vendor artifacts without leaking secrets.

## Commands

Run from `/docker/property`:

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
