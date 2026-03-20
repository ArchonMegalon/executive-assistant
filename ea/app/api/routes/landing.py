from __future__ import annotations

import html
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.dependencies import get_cloudflare_access_identity, get_container
from app.container import AppContainer
from app.services.cloudflare_access import CloudflareAccessIdentity
from app.services.google_oauth import build_google_oauth_start, complete_google_oauth_callback

router = APIRouter(tags=["landing"])


def _expected_api_token(container: AppContainer) -> str:
    return str(container.settings.auth.api_token or "").strip()


def _default_principal_id(container: AppContainer) -> str:
    return str(container.settings.auth.default_principal_id or "").strip() or "local-user"


def _token_required(container: AppContainer) -> bool:
    mode = str(getattr(getattr(container.settings, "runtime", None), "mode", "dev") or "dev").strip().lower() or "dev"
    return mode == "prod" or bool(_expected_api_token(container))


def _google_ready(container: AppContainer) -> tuple[bool, str]:
    state = container.provider_registry.binding_state("google_gmail")
    if state is None:
        return False, "google_gmail is not registered in the provider catalog."
    if not state.secret_configured:
        return False, "Google OAuth env vars are not configured yet."
    return True, "Google OAuth is configured and ready to connect."


def _gmail_onboarding_state(
    *,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> tuple[bool, bool]:
    if access_identity is None:
        return False, False
    normalized_email = access_identity.email.strip().lower()
    if not normalized_email.endswith("@gmail.com"):
        return False, False
    states = container.provider_registry.list_binding_states(principal_id=access_identity.principal_id)
    for state in states:
        if state.provider_key == "google_gmail" and state.binding_id:
            return True, True
    return True, False


def _page_shell(*, title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0f1117;
      --panel: #171b24;
      --muted: #9aa4b2;
      --text: #edf2f7;
      --line: #2a3342;
      --accent: #79c0ff;
      --accent-2: #8ddb8c;
      --danger: #ff8e8e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 16px/1.5 system-ui, sans-serif;
      background: radial-gradient(circle at top, #172132 0%, var(--bg) 48%);
      color: var(--text);
    }}
    main {{
      max-width: 920px;
      margin: 0 auto;
      padding: 32px 20px 64px;
    }}
    h1, h2 {{ margin: 0 0 12px; line-height: 1.1; }}
    p {{ margin: 0 0 14px; }}
    .lead {{ color: var(--muted); max-width: 62ch; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 18px;
      margin-top: 28px;
    }}
    .card {{
      background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01));
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.22);
    }}
    .status-ok {{ color: var(--accent-2); }}
    .status-warn {{ color: #ffd479; }}
    .status-bad {{ color: var(--danger); }}
    label {{ display: block; font-weight: 600; margin: 14px 0 6px; }}
    input, select {{
      width: 100%;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: #0d1118;
      color: var(--text);
      padding: 10px 12px;
    }}
    button {{
      margin-top: 18px;
      border: 0;
      border-radius: 12px;
      padding: 11px 16px;
      background: var(--accent);
      color: #08111c;
      font-weight: 700;
      cursor: pointer;
    }}
    code {{
      background: rgba(255,255,255,0.06);
      padding: 2px 6px;
      border-radius: 6px;
    }}
    .small {{ color: var(--muted); font-size: 0.95rem; }}
    .list {{ margin: 0; padding-left: 18px; color: var(--muted); }}
  </style>
</head>
<body>
  <main>{body}</main>
</body>
</html>"""
    )


@router.get("/", response_class=HTMLResponse)
def landing(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    google_ready, google_message = _google_ready(container)
    token_required = _token_required(container)
    default_principal = access_identity.principal_id if access_identity is not None else _default_principal_id(container)
    status_class = "status-ok" if google_ready else "status-warn"
    gmail_candidate, gmail_connected = _gmail_onboarding_state(container=container, access_identity=access_identity)
    access_block = ""
    principal_field = f"""
          <label for="principal_id">Principal ID</label>
          <input id="principal_id" name="principal_id" value="{html.escape(default_principal)}" required>
    """
    token_field = f"""
          <label for="api_token">API token</label>
          <input id="api_token" name="api_token" type="password" placeholder="{html.escape('required in prod or when EA_API_TOKEN is set' if token_required else 'optional in dev mode')}">
    """
    if access_identity is not None:
        access_block = f"""
        <p class="small"><strong>Signed in via Cloudflare Access:</strong> {html.escape(access_identity.email)}</p>
        <p class="small">EA uses that verified email to auto-provision your local assistant identity. There is no separate signup step here.</p>
        """
        principal_field = f"""
          <input type="hidden" name="principal_id" value="{html.escape(default_principal)}">
          <p class="small"><strong>Assistant principal:</strong> <code>{html.escape(default_principal)}</code></p>
        """
        token_field = ""
    gmail_note = ""
    if gmail_candidate and not gmail_connected:
        gmail_note = f"""
        <p class="status-ok">This looks like a Gmail user. Connect Google now to turn this into that user's own assistant.</p>
        <p class="small">EA already knows the verified Access email <code>{html.escape(access_identity.email if access_identity else '')}</code>. The next step is just Google consent.</p>
        """
    elif gmail_candidate and gmail_connected:
        gmail_note = """
        <p class="status-ok">Google is already linked for this assistant. The Gmail onboarding step is complete.</p>
        """
    body = f"""
    <h1>Executive Assistant</h1>
    <p class="lead">Principal-scoped control plane, durable context plane, queue-backed execution, and provider bindings. This front door is deliberately thin: connect a provider, verify the binding, then run real work.</p>
    <div class="grid">
      <section class="card">
        <h2>Google Gmail</h2>
        <p class="{status_class}">{html.escape(google_message)}</p>
        <p class="small">Current flow: OAuth connect, account listing, send-only Gmail smoke test. Mailbox read/verification is not enabled yet.</p>
        {access_block}
        {gmail_note}
        <form method="post" action="/google/connect">
          {principal_field}
          <label for="scope_bundle">Scope bundle</label>
          <select id="scope_bundle" name="scope_bundle">
            <option value="send">Send only</option>
            <option value="verify">Send + metadata verify</option>
          </select>
          {token_field}
          <button type="submit">Connect Google</button>
        </form>
      </section>
      <section class="card">
        <h2>What This Page Is For</h2>
        <ul class="list">
          <li>Start provider onboarding without hand-crafting API calls.</li>
          <li>Use Cloudflare Access as the tenant/user entry trigger.</li>
          <li>Keep the Google connect step honest about what the current Gmail slice can and cannot do.</li>
        </ul>
        <p class="small" style="margin-top:14px">If you want the raw API instead, the connect start lives at <code>/v1/providers/google/oauth/start</code>.</p>
      </section>
    </div>
    """
    return _page_shell(title="EA", body=body)


def _form_value(form_data: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form_data.get(key) or []
    return str(values[0] if values else default).strip()


@router.post("/google/connect")
async def google_connect_browser(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    body = (await request.body()).decode("utf-8", errors="ignore")
    form_data = urllib.parse.parse_qs(body, keep_blank_values=True)
    principal_id = _form_value(
        form_data,
        "principal_id",
        access_identity.principal_id if access_identity is not None else _default_principal_id(container),
    )
    scope_bundle = _form_value(form_data, "scope_bundle", "send")
    api_token = _form_value(form_data, "api_token", "")
    expected = _expected_api_token(container)
    if access_identity is None and _token_required(container):
        if not expected or str(api_token or "").strip() != expected:
            raise HTTPException(status_code=401, detail="auth_required")
    resolved_principal = str(principal_id or "").strip() or (
        access_identity.principal_id if access_identity is not None else _default_principal_id(container)
    )
    try:
        packet = build_google_oauth_start(
            principal_id=resolved_principal,
            scope_bundle=scope_bundle,
            redirect_uri_override=str(request.url_for("google_oauth_browser_callback")),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(packet.auth_url, status_code=303)


@router.get("/google/callback", response_class=HTMLResponse, name="google_oauth_browser_callback")
def google_oauth_browser_callback(
    code: str,
    state: str,
    container: AppContainer = Depends(get_container),
) -> HTMLResponse:
    try:
        account = complete_google_oauth_callback(container=container, code=code, state=state)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scopes = "".join(f"<li>{html.escape(scope)}</li>" for scope in account.granted_scopes)
    body = f"""
    <h1>Google Connected</h1>
    <p class="lead">The Gmail binding is now attached to principal <code>{html.escape(account.binding.principal_id)}</code>.</p>
    <div class="grid">
      <section class="card">
        <h2>Connected Account</h2>
        <p><strong>Email:</strong> {html.escape(account.google_email)}</p>
        <p><strong>Consent stage:</strong> {html.escape(account.consent_stage)}</p>
        <p><strong>Token status:</strong> {html.escape(account.token_status)}</p>
        <p><strong>Workspace mode:</strong> {html.escape(account.workspace_mode)}</p>
      </section>
      <section class="card">
        <h2>Granted Scopes</h2>
        <ul class="list">{scopes}</ul>
        <p class="small" style="margin-top:14px">Next practical step: run <code>POST /v1/providers/google/gmail/smoke-test</code> with the same principal.</p>
      </section>
    </div>
    """
    return _page_shell(title="EA Google Connected", body=body)
