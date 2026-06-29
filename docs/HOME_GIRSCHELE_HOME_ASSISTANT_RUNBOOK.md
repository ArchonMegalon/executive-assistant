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
5. Writes `.state/home-girschele/homeassistant-health.receipt.json`.

For individual actions:

```bash
bash scripts/home_girschele_hass_ops.sh migrate-config
bash scripts/home_girschele_hass_ops.sh up
bash scripts/home_girschele_hass_ops.sh restore-access
bash scripts/home_girschele_hass_ops.sh health
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
```

Then verify the live container mount:

```bash
docker inspect home-girschele-hass --format '{{range .Mounts}}{{if eq .Destination "/config"}}{{.Source}}{{end}}{{end}}'
```
