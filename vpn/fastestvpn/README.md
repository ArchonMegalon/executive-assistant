Place FastestVPN OpenVPN config files here.

Expected usage:
- copy one or more `*.ovpn` files from your FastestVPN manual/OpenVPN download set into this directory, or run `/docker/EA/scripts/bootstrap_fastestvpn_configs.sh`
- set `FASTESTVPN_USERNAME` and `FASTESTVPN_PASSWORD` in `.env`
- start EA with `docker compose -f docker-compose.yml -f docker-compose.fastestvpn.yml up -d --build --force-recreate ea-fastestvpn-proxy ea-api ea-worker ea-scheduler`

Notes:
- `docker-compose.fastestvpn.yml` randomizes the selected `.ovpn` file on recreate by default
- `scripts/rotate_fastestvpn_proxy.sh` recreates the proxy and EA services so BrowserAct picks up a fresh exit IP
- `*.ovpn` files are gitignored
