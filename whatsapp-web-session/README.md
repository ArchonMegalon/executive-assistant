# EA WhatsApp Web Session Sidecar

This optional sidecar gives EA a local HTTP bridge to a WhatsApp Web session.
It uses `whatsapp-web.js` with persistent `LocalAuth` storage in the `ea_whatsapp_web_session` Docker volume.

Start it with:

```sh
docker compose -f docker-compose.yml -f docker-compose.whatsapp-web-session.yml up -d ea-whatsapp-web-session
```

The sidecar logs may include the QR payload. Prefer the local pair page below and do not share raw logs.

To keep activation waiting in the background, start the optional activator too:

```sh
EA_WHATSAPP_WEB_ACTIVATOR_ENABLED=1 \
docker compose -f docker-compose.yml -f docker-compose.whatsapp-web-session.yml up -d ea-whatsapp-web-activator
```

The activator polls the sidecar and only enables the EA connector binding after the status endpoint reports `ready=true`.
It emits sanitized JSON status lines and does not print the QR payload.
To have it send one proof message after activation, set `EA_WHATSAPP_WEB_ACTIVATION_SEND_TEST=1` and `EA_WHATSAPP_WEB_LIVE_TEST_RECIPIENT` before starting it.
When proof mode is enabled, the activator keeps retrying until the proof send succeeds.

Check pairing state without exposing the QR payload:

```sh
python scripts/check_whatsapp_web_session_pairing.py
```

If you need the raw QR payload for a local QR renderer, use `--include-qr` and treat the output as sensitive.
You can also open the local scan page in a browser:

```text
http://127.0.0.1:8098/sessions/default-wa-web/pair
```

After the session is ready, the activator enables the EA binding automatically when it is running.
For one-shot manual activation, use:

```sh
EA_DEFAULT_PRINCIPAL_ID="${EA_DEFAULT_PRINCIPAL_ID:-principal-default}"
docker exec ea-scheduler python /app/scripts/activate_whatsapp_web_session.py \
  --binding-id ea-whatsapp-web-session \
  --principal-id "$EA_DEFAULT_PRINCIPAL_ID" \
  --session-ref default-wa-web \
  --browser-profile-ref docker-volume://ea_whatsapp_web_session \
  --session-api-base-url http://ea-whatsapp-web-session:8098
```

That command refuses to enable the binding unless the sidecar status endpoint reports `ready=true`.
Then prove delivery, or add `--send-test --recipient +15550101000` to the activation command:

```sh
EA_DEFAULT_PRINCIPAL_ID="${EA_DEFAULT_PRINCIPAL_ID:-principal-default}"
docker exec ea-scheduler python /app/scripts/send_whatsapp_web_session_live_test.py \
  --binding-id ea-whatsapp-web-session \
  --principal-id "$EA_DEFAULT_PRINCIPAL_ID" \
  --recipient +15550101000
```

If `EA_WHATSAPP_WEB_SESSION_API_TOKEN` is set, both the sidecar and EA binding must use the same token.
