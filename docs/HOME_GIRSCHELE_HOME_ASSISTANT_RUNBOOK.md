# home.girschele.com Home Assistant Runbook

`https://home.girschele.com` is a private Home Assistant endpoint exposed through the existing `chummer-run-cloudflared` tunnel. The public hostname must stay behind Cloudflare Access. Direct unauthenticated browser traffic should reach the Cloudflare Access login flow, not the Home Assistant onboarding or admin UI.

## Runtime Shape

- Compose file: `docker-compose.home-girschele.yml`
- Compose profile: `home-assistant`
- Service: `home-girschele-hass`
- Container: `home-girschele-hass`
- Image: `ghcr.io/home-assistant/home-assistant:${HOME_GIRSCHELE_HASS_IMAGE_TAG:-stable}`
- Network mode: `host`
- Local origin: `http://127.0.0.1:8123`
- Public origin route: `home.girschele.com -> http://172.17.0.1:8123` in the Cloudflare tunnel remote config
- Durable config path: `${HOME_GIRSCHELE_HASS_CONFIG_DIR:-/docker/EA/.state/home-girschele/homeassistant-config}`

The HA config must not live under `/tmp`. The current reverse-proxy settings are required because Cloudflare Tunnel sends forwarded headers from the Docker bridge network:

```yaml
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 192.168.96.0/24
```

## Standard Operations

Run all commands from `/docker/EA`.

```bash
bash scripts/home_girschele_hass_ops.sh harden
```

That performs the full operator path:

1. Migrates the existing `/config` mount into the durable config directory.
2. Ensures the reverse-proxy settings are present.
3. Starts `home-girschele-hass` through compose with the `home-assistant` profile.
4. Restores the Cloudflare Access app for `home.girschele.com`.
5. Creates a durable config/state backup and non-destructive restore drill receipt.
6. Writes health, drift, and disk/log receipts under `.state/home-girschele/`.

For individual actions:

```bash
bash scripts/home_girschele_hass_ops.sh migrate-config
bash scripts/home_girschele_hass_ops.sh up
bash scripts/home_girschele_hass_ops.sh restore-access
bash scripts/home_girschele_hass_ops.sh health
bash scripts/home_girschele_hass_ops.sh backup
bash scripts/home_girschele_hass_ops.sh restore-drill
bash scripts/home_girschele_hass_ops.sh drift
bash scripts/home_girschele_hass_ops.sh disk-log
bash scripts/home_girschele_hass_ops.sh scheduled-health
bash scripts/home_girschele_hass_ops.sh install-scheduled-health
```

## Health Contract

`scripts/home_girschele_hass_ops.sh health` must prove:

- HA local frontend returns a Home Assistant page.
- HA local API returns `401`, proving the API is routed but unauthenticated access is denied.
- HA local WebSocket upgrades with `101`.
- Public unauthenticated traffic redirects to Cloudflare Access.
- `/.well-known/cloudflare-access-protected-resource/` reports the hostname as protected.
- A configured Cloudflare Access service token can reach the HA frontend, API, and WebSocket through the public hostname.
- HA config is outside `/tmp` and includes the reverse-proxy trust block.

The receipt intentionally does not store tokens or raw credential values.

## Backup And Restore Proof

`backup` creates an ignored archive under `.state/home-girschele/backups/` and writes `.state/home-girschele/homeassistant-backup.receipt.json`. The archive contains Home Assistant config and state files, including `.storage/*` and `home-assistant_v2.db`, while excluding runtime logs and `.ha_run.lock`.

`restore-drill` extracts the latest backup into a temporary directory and runs Home Assistant's config checker against that extracted copy. It writes `.state/home-girschele/homeassistant-restore-drill.receipt.json`. This is intentionally non-destructive: it proves the backup can be unpacked and parsed without replacing the live `/config`.

## Drift And Pressure Monitoring

`drift` writes `.state/home-girschele/homeassistant-drift.receipt.json` and fails closed if any of these drift:

- the live container is not running;
- `/config` is not mounted from `/docker/EA/.state/home-girschele/homeassistant-config`;
- the container is no longer on host networking;
- Docker log rotation is not `10m` times `3`;
- unauthenticated public traffic no longer redirects to Cloudflare Access;
- Cloudflare's protected-resource metadata no longer reports `protected: true`;
- the current `chummer-run-cloudflared` tunnel log no longer includes `home.girschele.com -> http://172.17.0.1:8123`;
- the Cloudflare Access app no longer has service-token and email allow policies.

`disk-log` writes `.state/home-girschele/homeassistant-disk-log.receipt.json` and checks free space for the HA config filesystem and `/var/lib/docker`, plus the live Docker JSON log size and rotation settings.

## Scheduled Health

`scheduled-health` is the cron/systemd-safe entrypoint. It reuses the normal `health` receipt contract and then runs `drift` and `disk-log`; the wrapper receipt is `.state/home-girschele/homeassistant-scheduled-health.receipt.json`.

`install-scheduled-health` installs a user systemd timer named `home-girschele-health.timer` that runs every 15 minutes. It writes `.state/home-girschele/homeassistant-schedule-install.receipt.json`. If a host does not support user systemd, keep the generated service/timer files as the source and install an equivalent cron entry that runs:

```bash
cd /docker/EA && bash scripts/home_girschele_hass_ops.sh scheduled-health
```

## Safe Onboarding/Admin Path

The public hostname must never expose Home Assistant onboarding or admin pages directly. The safe operator path is:

1. Open `https://home.girschele.com`.
2. Confirm the first page is the Cloudflare Access login flow.
3. Authenticate with one of the allowed operator emails.
4. Only after Cloudflare Access succeeds, complete Home Assistant onboarding or admin work.

The testable invariant is the unauthenticated probe: `curl -k -I https://home.girschele.com/` must return a redirect to `girschele.cloudflareaccess.com`, and the protected-resource metadata must report `protected: true`.
The `drift` receipt also probes `/onboarding.html`, `/config`, and `/lovelace` without credentials and requires all of them to redirect to Cloudflare Access.

## Recovery

If HA is down:

```bash
docker logs --tail 200 home-girschele-hass
bash scripts/home_girschele_hass_ops.sh up
bash scripts/home_girschele_hass_ops.sh health
```

If the tunnel route is wrong:

```bash
docker logs --tail 120 chummer-run-cloudflared
```

Look for a remote ingress rule containing:

```json
{"hostname":"home.girschele.com","service":"http://172.17.0.1:8123"}
```

If public traffic reaches HA without Cloudflare Access:

```bash
bash scripts/home_girschele_hass_ops.sh restore-access
bash scripts/home_girschele_hass_ops.sh health
```

If the config path regresses to `/tmp`:

```bash
bash scripts/home_girschele_hass_ops.sh migrate-config
bash scripts/home_girschele_hass_ops.sh up
bash scripts/home_girschele_hass_ops.sh backup
bash scripts/home_girschele_hass_ops.sh restore-drill
```

Then verify the live container mount:

```bash
docker inspect home-girschele-hass --format '{{range .Mounts}}{{if eq .Destination "/config"}}{{.Source}}{{end}}{{end}}'
```
