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
5. Creates a durable config/state backup, replicates it to pCloud, and proves restore from the replicated copy.
6. Snapshots Cloudflare tunnel and Access app configuration for drift review.
7. Writes health, drift, disk/log, alert, and status receipts under `.state/home-girschele/`.

For individual actions:

```bash
bash scripts/home_girschele_hass_ops.sh migrate-config
bash scripts/home_girschele_hass_ops.sh up
bash scripts/home_girschele_hass_ops.sh restore-access
bash scripts/home_girschele_hass_ops.sh health
bash scripts/home_girschele_hass_ops.sh backup
bash scripts/home_girschele_hass_ops.sh replicate-backup
bash scripts/home_girschele_hass_ops.sh restore-drill
bash scripts/home_girschele_hass_ops.sh restore-replica-drill
bash scripts/home_girschele_hass_ops.sh restore-replica-start-drill
bash scripts/home_girschele_hass_ops.sh drift
bash scripts/home_girschele_hass_ops.sh disk-log
bash scripts/home_girschele_hass_ops.sh snapshot-cloudflare
bash scripts/home_girschele_hass_ops.sh alert-check
bash scripts/home_girschele_hass_ops.sh alert-drill
bash scripts/home_girschele_hass_ops.sh status
bash scripts/home_girschele_hass_ops.sh publish-status
bash scripts/home_girschele_hass_ops.sh freshness
bash scripts/home_girschele_hass_ops.sh restore-inventory
bash scripts/home_girschele_hass_ops.sh incident-drill
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

## Off-Host Replication

`replicate-backup` copies the latest local backup and manifest to `${HOME_GIRSCHELE_REPLICA_DIR:-/mnt/pcloud/EA/home-girschele/homeassistant-backups}` and writes `.state/home-girschele/homeassistant-replication.receipt.json`. The receipt verifies the copied archive checksum, records the mount source/fstype, and fails closed if the target resolves back into `.state/home-girschele/` instead of a mounted `/mnt/*` target.

Retention defaults:

- local backups: `${HOME_GIRSCHELE_LOCAL_RETENTION_COUNT:-14}`
- replicated backups: `${HOME_GIRSCHELE_REPLICA_RETENTION_COUNT:-30}`

`restore-replica-drill` extracts the latest replicated archive and runs Home Assistant's config checker inside a fresh disposable Home Assistant container. It writes `.state/home-girschele/homeassistant-replica-restore-drill.receipt.json`.

`restore-replica-start-drill` goes further: it extracts the latest replicated archive, starts a disposable Home Assistant container on a random localhost port, waits until the restored instance serves HTTP, writes `.state/home-girschele/homeassistant-replica-start-drill.receipt.json`, and removes the container. This proves the replicated backup can start, not only pass static config validation.

## Cloudflare Snapshot And Access Recovery

`restore-access` now resolves the configured Cloudflare Access service token by the current `CODEXLIZ_CF_ACCESS_CLIENT_ID` and writes `.state/home-girschele/homeassistant-cloudflare-access.receipt.json`. The Access policy must use a named `service_token.token_id` selector; broad `any_valid_service_token` is treated as drift.

`snapshot-cloudflare` exports the current Cloudflare tunnel config and Access app JSON under `.state/home-girschele/cloudflare-snapshots/<timestamp>/` and writes `.state/home-girschele/homeassistant-cloudflare-snapshot.receipt.json`. The snapshot receipt verifies:

- the tunnel still routes `home.girschele.com -> http://172.17.0.1:8123`;
- the Access app exists;
- the named service-token policy is present.

## Drift And Pressure Monitoring

`drift` writes `.state/home-girschele/homeassistant-drift.receipt.json` and fails closed if any of these drift:

- the live container is not running;
- `/config` is not mounted from `/docker/EA/.state/home-girschele/homeassistant-config`;
- the container is no longer on host networking;
- Docker log rotation is not `10m` times `3`;
- unauthenticated public traffic no longer redirects to Cloudflare Access;
- Cloudflare's protected-resource metadata no longer reports `protected: true`;
- the current `chummer-run-cloudflared` tunnel log no longer includes `home.girschele.com -> http://172.17.0.1:8123`;
- the Cloudflare Access app no longer has the named service-token policy and email allow policy.

`disk-log` writes `.state/home-girschele/homeassistant-disk-log.receipt.json` and checks free space for the HA config filesystem and `/var/lib/docker`, plus the live Docker JSON log size and rotation settings.

## Alert Delivery

`alert-check` watches the latest health, drift, and disk/log receipts. If any are missing or not `pass`, it sends an operator alert through EA live ops WhatsApp when available and falls back to the configured Telegram bot/chat. It writes `.state/home-girschele/homeassistant-alert.receipt.json`.

`alert-drill` uses a synthetic failed receipt so the delivery route can be tested without breaking Home Assistant. Set `HOME_GIRSCHELE_ALERT_DRY_RUN=true` to prove wiring without sending a real operator message.

The script probes `ea-whatsapp-web-session` before using WhatsApp. If the sidecar is stopped, unreachable, or requires QR re-authentication, the receipt explicitly records WhatsApp as replaced and sends through Telegram as the live operator transport. Re-enable WhatsApp by restoring the WhatsApp Web session, then rerun:

```bash
docker compose -f docker-compose.whatsapp-web-session.yml up -d ea-whatsapp-web-session
bash scripts/home_girschele_hass_ops.sh alert-drill
```

## Status Board And Incident Drill

`status` writes `.state/home-girschele/homeassistant-status.md` and `.state/home-girschele/homeassistant-status.receipt.json` with the latest receipt statuses.

`publish-status` copies the status markdown and receipt to `${HOME_GIRSCHELE_STATUS_PUBLISH_DIR:-/mnt/pcloud/EA/home-girschele/status}` and writes `.state/home-girschele/homeassistant-status-publish.receipt.json`. The publish receipt verifies the target is a mounted `/mnt/*` location instead of the local EA state directory.

`incident-drill` runs the recovery chain as subprocesses and writes `.state/home-girschele/homeassistant-incident-drill.receipt.json`:

1. snapshot Cloudflare tunnel and Access app;
2. reapply named-token Cloudflare Access recovery;
3. create a local backup;
4. replicate the backup off host;
5. restore-check the replicated backup in a fresh disposable container;
6. start the replicated backup in a disposable Home Assistant container and prove HTTP;
7. rerun drift, health, alert-check, restore-inventory, freshness, and status.

## Freshness SLOs

`freshness` writes `.state/home-girschele/homeassistant-freshness.receipt.json` and fails if required receipts are missing, not `pass`, or stale.

Default freshness limits:

- backup receipt: `${HOME_GIRSCHELE_MAX_BACKUP_AGE_SECONDS:-86400}`
- replicated backup receipt: `${HOME_GIRSCHELE_MAX_REPLICA_AGE_SECONDS:-86400}`
- Cloudflare snapshot receipt: `${HOME_GIRSCHELE_MAX_CLOUDFLARE_SNAPSHOT_AGE_SECONDS:-86400}`
- scheduled health receipt: `${HOME_GIRSCHELE_MAX_SCHEDULED_HEALTH_AGE_SECONDS:-1800}`
- incident drill receipt: `${HOME_GIRSCHELE_MAX_INCIDENT_DRILL_AGE_SECONDS:-604800}`

## Host-Loss Restore Inventory

`restore-inventory` writes `.state/home-girschele/homeassistant-restore-inventory.json` and `.state/home-girschele/homeassistant-restore-inventory.receipt.json`. The inventory is no-secret: it records required paths, sizes, and hashes for non-secret artifacts, and only records presence of required secret keys for secret files.

It verifies that a host-loss restore has:

- the latest replicated backup archive and manifest;
- this runbook's compose service and ops script;
- Cloudflare tunnel and Access app snapshots;
- the Cloudflare Access service-token env file;
- the Cloudflare API env file.

## Scheduled Health

`scheduled-health` is the cron/systemd-safe entrypoint. It reuses the normal `health` receipt contract and then runs `drift`, `disk-log`, `freshness`, and `alert-check`; the wrapper receipt is `.state/home-girschele/homeassistant-scheduled-health.receipt.json`.

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
bash scripts/home_girschele_hass_ops.sh snapshot-cloudflare
```

If the config path regresses to `/tmp`:

```bash
bash scripts/home_girschele_hass_ops.sh migrate-config
bash scripts/home_girschele_hass_ops.sh up
bash scripts/home_girschele_hass_ops.sh backup
bash scripts/home_girschele_hass_ops.sh restore-drill
bash scripts/home_girschele_hass_ops.sh replicate-backup
bash scripts/home_girschele_hass_ops.sh restore-replica-drill
bash scripts/home_girschele_hass_ops.sh restore-replica-start-drill
bash scripts/home_girschele_hass_ops.sh restore-inventory
```

Then verify the live container mount:

```bash
docker inspect home-girschele-hass --format '{{range .Mounts}}{{if eq .Destination "/config"}}{{.Source}}{{end}}{{end}}'
```
