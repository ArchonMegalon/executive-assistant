# PropertyQuarry Tour Ops

## Purpose

Use this internal EA operator skill when PropertyQuarry needs licensed 3D-tour tooling, a vendor export, or a human-provided artifact that cannot be fetched safely through normal runtime automation.

Typical examples:

- paid desktop installers such as Pano2VR, 3DVista, WPVR Pro, or krpano tools
- account-side exports from licensed desktop/web apps
- verified 3D-tour exports, panoramas, cubemaps, walkthrough videos, or private viewer bundles
- user-dropped files in pCloud, Downloads, or prepared import folders
- Telegram asks when the operator must download, export, upload, or confirm something manually
- release-gate receipts proving that Matterport, 3DVista, Pano2VR, krpano, and MagicFit modes are playable

This skill is not a product-facing user feature. It is an operator lane for unblocking release evidence without leaking secrets or accepting fake readiness.

## Rules

- First try local credentials, configured APIs, existing caches, and prepared import folders.
- Treat browser-only login, paid desktop export, Cloudflare challenge, physical media, or missing user file as an external artifact blocker.
- Send a concrete Telegram ask when the blocker cannot be solved autonomously.
- Never store raw passwords, bot tokens, license keys, private invoice signatures, reset links, or session cookies in tracked files.
- Store proprietary installers, vendor apps, and generated exports only in ignored runtime folders.
- Do not count ownership receipts, placeholder HTML, screenshot galleries, or generated fallback pages as playable 3D-tour evidence.
- Every imported artifact needs a machine-readable receipt and a verifier result.
- A paid license proves entitlement; it does not prove product readiness. Product readiness requires a generated or hosted playable tour that the public route can load.
- If a GUI tool is necessary, use Wine/Xvfb automation where reasonable, but stop before unsafe secret entry or destructive account-side changes.
- If a provider cannot be automated, send one concrete Telegram ask with the exact missing file/export and the drop path.

## Standard Paths

- User drop: `/mnt/pcloud/EA`
- PropertyQuarry repo: `/docker/property`
- Installer cache: `/docker/property/state/vendor_installers`
- Vendor apps: `/docker/property/state/vendor_apps`
- Incoming tour exports: `/docker/property/state/incoming_property_tours/<slug>/<provider>/`
- Public tour volume: `/var/lib/docker/volumes/property_propertyquarry_public_tours/_data`
- Receipts: `/docker/property/_completion/tours`

## Workflow

1. Establish the missing provider or artifact.
   - Run the current PropertyQuarry verifier before asking for anything.
   - Read the missing provider mode from the verifier output instead of guessing.
   - Prefer fixing only the missing evidence, not rerunning all provider work.

2. Discover candidate files.
   - Prefer `/mnt/pcloud/EA`, `~/Downloads`, repo `state/vendor_installers`, and repo `state/incoming_property_tours`.
   - Avoid broad scans of sensitive roots unless explicitly requested.

3. Cache or stage the artifact.
   - Copy installers to `state/vendor_installers`.
   - Copy complete exports to `state/incoming_property_tours/<slug>/<provider>/`.
   - Keep proprietary binaries and exports out of git.

4. Install or launch licensed tools only when needed.
   - Prefer vendor-native export folders when they already exist.
   - Use Wine/Xvfb for Windows desktop tools when the host has no native GUI path.
   - Capture screenshots and command receipts for GUI progress.
   - Do not paste raw credentials into logs or tracked files.

5. Generate or validate the vendor export.
   - 3DVista exports must contain real 3DVista runtime assets, for example `tdvplayer.js` or equivalent publish output.
   - Pano2VR exports must contain real Pano2VR runtime assets, for example `pano2vr_player.js`, `pano.xml`, `gginfo.json`, `ggpkg`, or `ggskin`.
   - krpano output must be a real scene/panorama/cubemap tour, not a static gallery.
   - MagicFit output must be receipt-backed playable walkthrough media.

6. Import and verify the artifact.
   - Use the repo verifier for the artifact type.
   - For tour tooling, run `scripts/verify_property_tour_vendor_tooling.py`.
   - For imported tours, run discovery/import first, then `scripts/verify_property_tour_controls.py`.

7. If blocked, notify the operator.
   - Send a Telegram message with exact action, direct link if safe, filename pattern, target folder, and why it is needed.
   - Store a redacted receipt under `_completion`.

8. Continue the release loop.
   - When the artifact appears, import it, verify it, update the release manifest/status, and deploy only after the gate is truthful.

## Release Gate

A provider mode is ready only when all of these are true:

- the source artifact exists in an ignored runtime folder or an allowlisted hosted source
- the importer or route registration has a machine-readable receipt
- `scripts/verify_property_tour_controls.py` reports the provider mode as ready
- the live public route returns a usable HTTP response with provider runtime markers
- the release manifest names the evidence and any remaining blockers

Do not mark PropertyQuarry gold while `scripts/propertyquarry_gold_status.py` reports `blocked`.

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

Refresh the gold gate:

```bash
python3 scripts/propertyquarry_gold_status.py \
  --write _completion/propertyquarry-gold-status-current.json
```
