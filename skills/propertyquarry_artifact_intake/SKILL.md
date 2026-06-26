# PropertyQuarry Artifact Intake

## Purpose

Use this internal EA operator skill when PropertyQuarry needs an external artifact that cannot be fetched safely through normal runtime automation.

Typical examples:

- paid desktop installers such as Pano2VR, 3DVista, WPVR Pro, or krpano tools
- account-side exports from licensed desktop/web apps
- verified 3D-tour exports, panoramas, cubemaps, walkthrough videos, or private viewer bundles
- user-dropped files in pCloud, Downloads, or prepared import folders
- Telegram asks when the operator must download, export, upload, or confirm something manually

This skill is not a product-facing user feature. It is an operator lane for unblocking release evidence without leaking secrets or accepting fake readiness.

## Rules

- First try local credentials, configured APIs, existing caches, and prepared import folders.
- Treat browser-only login, paid desktop export, Cloudflare challenge, physical media, or missing user file as an external artifact blocker.
- Send a concrete Telegram ask when the blocker cannot be solved autonomously.
- Never store raw passwords, bot tokens, license keys, private invoice signatures, reset links, or session cookies in tracked files.
- Store proprietary installers, vendor apps, and generated exports only in ignored runtime folders.
- Do not count ownership receipts, placeholder HTML, screenshot galleries, or generated fallback pages as playable 3D-tour evidence.
- Every imported artifact needs a machine-readable receipt and a verifier result.

## Standard Paths

- User drop: `/mnt/pcloud/EA`
- PropertyQuarry repo: `/docker/property`
- Installer cache: `/docker/property/state/vendor_installers`
- Vendor apps: `/docker/property/state/vendor_apps`
- Incoming tour exports: `/docker/property/state/incoming_property_tours/<slug>/<provider>/`
- Public tour volume: `/var/lib/docker/volumes/property_propertyquarry_public_tours/_data`
- Receipts: `/docker/property/_completion/tours`

## Workflow

1. Discover candidate files.
   - Prefer `/mnt/pcloud/EA`, `~/Downloads`, repo `state/vendor_installers`, and repo `state/incoming_property_tours`.
   - Avoid broad scans of sensitive roots unless explicitly requested.

2. Cache or stage the artifact.
   - Copy installers to `state/vendor_installers`.
   - Copy complete exports to `state/incoming_property_tours/<slug>/<provider>/`.
   - Keep proprietary binaries and exports out of git.

3. Verify the artifact.
   - Use the repo verifier for the artifact type.
   - For tour tooling, run `scripts/verify_property_tour_vendor_tooling.py`.
   - For imported tours, run discovery/import first, then `scripts/verify_property_tour_controls.py`.

4. If blocked, notify the operator.
   - Send a Telegram message with exact action, direct link if safe, filename pattern, target folder, and why it is needed.
   - Store a redacted receipt under `_completion`.

5. Continue the release loop.
   - When the artifact appears, import it, verify it, update the release manifest/status, and deploy only after the gate is truthful.

## PropertyQuarry Tour Evidence

3D-tour gold requires playable evidence, not ownership evidence.

Accepted evidence:

- Matterport: verified hosted control route with safe manifest/private receipt
- 3DVista: verified export containing provider runtime markers or allowlisted hosted 3DVista URL
- Pano2VR: verified export containing provider runtime markers such as `pano2vr`, `ggpkg`, `ggskin`, `pano.xml`, or `tour.js`
- krpano: real walkable scene/panorama assets, not a plain image gallery
- MagicFit: receipt-backed playable walkthrough media

Rejected evidence:

- placeholder HTML
- static photo galleries
- empty provider fields
- license ownership receipts without a generated export
- private URLs leaked into public receipts

## Commands

Discover a synced Pano2VR installer:

```bash
python3 ~/.codex/skills/ea-artifact-intake/scripts/artifact_intake.py discover \
  --pattern '*pano2vr*.exe' \
  --root /mnt/pcloud/EA \
  --root "$HOME/Downloads"
```

Cache the first matching installer:

```bash
python3 ~/.codex/skills/ea-artifact-intake/scripts/artifact_intake.py cache-first \
  --pattern '*pano2vr*.exe' \
  --root /mnt/pcloud/EA \
  --target-dir /docker/property/state/vendor_installers
```

Send an operator ask:

```bash
python3 ~/.codex/skills/ea-artifact-intake/scripts/artifact_intake.py telegram \
  --env-file /docker/property/.env \
  --chat-id "$TELEGRAM_CHAT_ID" \
  --text 'Please drop the complete Pano2VR export zip into /mnt/pcloud/EA.'
```

Verify tour tooling from the PropertyQuarry repo:

```bash
python3 scripts/verify_property_tour_vendor_tooling.py \
  --write _completion/tours/property-tour-vendor-tooling-current.json
```

Verify hosted tour controls:

```bash
python3 scripts/verify_property_tour_controls.py \
  --tour-root /var/lib/docker/volumes/property_propertyquarry_public_tours/_data \
  --write _completion/tours/property-tour-controls-current.json
```
