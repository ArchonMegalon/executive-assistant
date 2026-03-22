from __future__ import annotations

import html
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.dependencies import get_cloudflare_access_identity, get_container
from app.container import AppContainer
from app.services.cloudflare_access import CloudflareAccessIdentity
from app.services.google_oauth import complete_google_oauth_callback

router = APIRouter(tags=["landing"])


def _expected_api_token(container: AppContainer) -> str:
    return str(container.settings.auth.api_token or "").strip()


def _default_principal_id(container: AppContainer) -> str:
    return str(container.settings.auth.default_principal_id or "").strip() or "local-user"


def _token_required(container: AppContainer) -> bool:
    mode = str(getattr(getattr(container.settings, "runtime", None), "mode", "dev") or "dev").strip().lower() or "dev"
    return mode == "prod" or bool(_expected_api_token(container))


def _status_tone(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"connected", "ready_to_connect", "ready_for_brief", "completed"}:
        return "good"
    if normalized in {"planned_business", "export_planned", "guided_manual", "bot_link_requested", "available"}:
        return "warn"
    if normalized in {"credentials_missing", "planned_not_available"}:
        return "bad"
    return "muted"


def _nav(current: str) -> str:
    items = [
        ("/", "Assistant", "home"),
        ("/setup", "Setup", "setup"),
        ("/demo/brief", "Sample Brief", "brief"),
        ("/privacy", "Privacy", "privacy"),
    ]
    links = []
    for href, label, key in items:
        active = " active" if key == current else ""
        links.append(f'<a class="nav-link{active}" href="{href}">{html.escape(label)}</a>')
    return "".join(links)


def _page_shell(*, title: str, body: str, current: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f4eee3;
      --bg-2: #ece2d1;
      --panel: rgba(255, 250, 243, 0.94);
      --panel-strong: rgba(255, 255, 255, 0.98);
      --line: #d5c3ac;
      --ink: #1a2833;
      --muted: #5c6873;
      --accent: #0f6c5b;
      --accent-2: #b7632d;
      --good: #1d7a49;
      --warn: #9c6628;
      --bad: #a64234;
      --shadow: 0 18px 45px rgba(40, 33, 26, 0.12);
      color-scheme: light;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(15,108,91,0.12), transparent 32%),
        radial-gradient(circle at top right, rgba(183,99,45,0.14), transparent 36%),
        linear-gradient(180deg, var(--bg) 0%, #f9f5ef 58%, #f1e8da 100%);
      font: 16px/1.6 "IBM Plex Sans", "Segoe UI", sans-serif;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    main {{ max-width: 1160px; margin: 0 auto; padding: 24px 20px 72px; }}
    nav {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 28px;
    }}
    .brand {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      font-weight: 700;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .brand-dot {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      box-shadow: 0 0 0 6px rgba(15,108,91,0.08);
    }}
    .nav-group {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .nav-link {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 14px;
      background: rgba(255,255,255,0.55);
      color: var(--ink);
      font-size: 0.95rem;
    }}
    .nav-link.active {{
      background: var(--ink);
      border-color: var(--ink);
      color: #fff6eb;
    }}
    h1, h2, h3 {{
      margin: 0 0 12px;
      line-height: 1.05;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
      font-weight: 700;
      letter-spacing: -0.02em;
    }}
    h1 {{ font-size: clamp(2.4rem, 5vw, 4.4rem); max-width: 12ch; }}
    h2 {{ font-size: clamp(1.5rem, 3vw, 2.1rem); }}
    h3 {{ font-size: 1.1rem; }}
    p {{ margin: 0 0 14px; }}
    .hero {{
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 22px;
      align-items: stretch;
      margin-bottom: 28px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 22px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}
    .card-strong {{
      background: var(--panel-strong);
    }}
    .lead {{
      color: var(--muted);
      max-width: 56ch;
      font-size: 1.06rem;
    }}
    .cta-row {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 20px;
    }}
    .cta {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 14px;
      padding: 11px 16px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
      color: var(--ink);
      font-weight: 700;
    }}
    .cta.primary {{
      background: linear-gradient(135deg, var(--accent), #175d7d);
      color: #f6f4ef;
      border-color: transparent;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 18px;
      margin-top: 18px;
    }}
    .grid-2 {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 18px;
      margin-top: 18px;
    }}
    .eyebrow {{
      margin-bottom: 10px;
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.78rem;
      font-weight: 700;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 0.84rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .pill.good {{ background: rgba(29,122,73,0.12); color: var(--good); }}
    .pill.warn {{ background: rgba(156,102,40,0.14); color: var(--warn); }}
    .pill.bad {{ background: rgba(166,66,52,0.12); color: var(--bad); }}
    .pill.muted {{ background: rgba(92,104,115,0.12); color: var(--muted); }}
    .stack > * + * {{ margin-top: 12px; }}
    .list {{
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
    }}
    .list li + li {{ margin-top: 8px; }}
    .mini {{
      color: var(--muted);
      font-size: 0.94rem;
    }}
    .surface {{
      border: 1px dashed var(--line);
      border-radius: 18px;
      padding: 16px;
      background: rgba(255,255,255,0.55);
    }}
    .signal-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
      margin-top: 18px;
    }}
    .signal {{
      border-radius: 16px;
      padding: 14px;
      background: rgba(255,255,255,0.72);
      border: 1px solid rgba(213,195,172,0.8);
    }}
    .signal strong {{
      display: block;
      font-size: 1.3rem;
      line-height: 1.1;
      margin-bottom: 4px;
    }}
    form {{
      display: block;
      margin: 0;
    }}
    label {{
      display: block;
      font-weight: 700;
      margin: 12px 0 6px;
    }}
    input, select, textarea {{
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: #fffdf9;
      color: var(--ink);
      padding: 11px 12px;
      font: inherit;
    }}
    textarea {{ min-height: 96px; resize: vertical; }}
    .checks {{
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }}
    .check {{
      display: flex;
      align-items: center;
      gap: 10px;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px 12px;
      background: rgba(255,255,255,0.72);
      font-weight: 500;
    }}
    .check input {{
      width: auto;
      margin: 0;
      padding: 0;
    }}
    button {{
      margin-top: 16px;
      border: 0;
      border-radius: 14px;
      padding: 12px 16px;
      background: linear-gradient(135deg, var(--accent), #175d7d);
      color: #f6f4ef;
      font-weight: 700;
      cursor: pointer;
    }}
    .split {{
      display: flex;
      gap: 14px;
      flex-wrap: wrap;
    }}
    .split > * {{
      flex: 1 1 220px;
    }}
    @media (max-width: 840px) {{
      .hero {{
        grid-template-columns: 1fr;
      }}
      main {{
        padding-left: 16px;
        padding-right: 16px;
      }}
      h1 {{
        max-width: none;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <nav>
      <div class="brand"><span class="brand-dot"></span> Executive Assistant</div>
      <div class="nav-group">{_nav(current)}</div>
    </nav>
    {body}
  </main>
</body>
</html>"""
    )


def _form_value(form_data: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form_data.get(key) or []
    return str(values[0] if values else default).strip()


def _form_values(form_data: dict[str, list[str]], key: str) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in (form_data.get(key) or []) if str(value).strip())


def _checked(value: bool) -> str:
    return " checked" if value else ""


def _selected(current: str, expected: str) -> str:
    return " selected" if str(current or "").strip().lower() == str(expected or "").strip().lower() else ""


def _principal_for_page(
    *,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> str:
    if access_identity is not None:
        return access_identity.principal_id
    return _default_principal_id(container)


def _load_status(
    *,
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> tuple[str, dict[str, object]]:
    principal_id = _principal_for_page(container=container, access_identity=access_identity)
    return principal_id, container.onboarding.status(principal_id=principal_id)


def _status_card(title: str, channel: dict[str, object], href: str) -> str:
    tone = _status_tone(str(channel.get("status") or ""))
    detail = html.escape(str(channel.get("detail") or ""))
    status = html.escape(str(channel.get("status") or "not_selected").replace("_", " "))
    summary = html.escape(str(channel.get("bundle_summary") or channel.get("history_import_posture") or ""))
    return f"""
    <section class="card">
      <div class="split" style="align-items:start">
        <div>
          <h3>{html.escape(title)}</h3>
          <p class="mini">{detail}</p>
          {f'<p class="mini"><strong>Contract:</strong> {summary}</p>' if summary else ''}
        </div>
        <span class="pill {tone}">{status}</span>
      </div>
      <p class="mini" style="margin-top:14px"><a href="{href}">Channel details</a></p>
    </section>
    """


def _render_list(items: object, *, fallback: str) -> str:
    rows = [str(item).strip() for item in (items or []) if str(item).strip()]
    if not rows:
        return f"<li>{html.escape(fallback)}</li>"
    return "".join(f"<li>{html.escape(row)}</li>" for row in rows)


def _browser_form_context(
    *,
    form_data: dict[str, list[str]],
    container: AppContainer,
    access_identity: CloudflareAccessIdentity | None,
) -> str:
    expected = _expected_api_token(container)
    if access_identity is None and _token_required(container):
        api_token = _form_value(form_data, "api_token", "")
        if not expected or api_token != expected:
            raise HTTPException(status_code=401, detail="auth_required")
    principal_id = _form_value(
        form_data,
        "principal_id",
        access_identity.principal_id if access_identity is not None else _default_principal_id(container),
    )
    return principal_id or _default_principal_id(container)


def _shared_browser_fields(
    *,
    principal_id: str,
    access_identity: CloudflareAccessIdentity | None,
    container: AppContainer,
) -> str:
    token_field = ""
    if access_identity is None and _token_required(container):
        token_field = """
        <label for="api_token">API token</label>
        <input id="api_token" name="api_token" type="password" placeholder="required for browser setup on this host">
        """
    if access_identity is not None:
        return f"""
        <input type="hidden" name="principal_id" value="{html.escape(principal_id)}">
        {token_field}
        """
    return f"""
    <label for="principal_id">Principal ID</label>
    <input id="principal_id" name="principal_id" value="{html.escape(principal_id)}" required>
    {token_field}
    """


def _status_header(
    *,
    principal_id: str,
    access_identity: CloudflareAccessIdentity | None,
    status: dict[str, object],
) -> str:
    workspace = dict(status.get("workspace") or {})
    current_status = html.escape(str(status.get("status") or "draft").replace("_", " "))
    next_step = html.escape(str(status.get("next_step") or "Start setup."))
    signed_in = ""
    if access_identity is not None:
        signed_in = f"""
        <p class="mini"><strong>Signed in via Cloudflare Access:</strong> {html.escape(access_identity.email)}<br>
        <strong>Principal:</strong> <code>{html.escape(principal_id)}</code></p>
        """
    return f"""
    <section class="card card-strong">
      <div class="eyebrow">Current Assistant State</div>
      <div class="split" style="align-items:start">
        <div>
          <h2>{html.escape(str(workspace.get("name") or "Assistant setup"))}</h2>
          <p class="lead">The assistant state is principal-scoped, durable in Postgres when configured, and honest about which channels are real, guided, or still planned.</p>
        </div>
        <span class="pill {_status_tone(str(status.get('status') or 'draft'))}">{current_status}</span>
      </div>
      {signed_in}
      <p><strong>Next step:</strong> {next_step}</p>
    </section>
    """


@router.get("/", response_class=HTMLResponse)
def landing(
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    channels = dict(status.get("channels") or {})
    brief_preview = dict(status.get("brief_preview") or {})
    workspace = dict(status.get("workspace") or {})
    storage_posture = dict(status.get("storage_posture") or {})
    assistant_modes = list(status.get("assistant_modes") or [])
    featured_domains = list(status.get("featured_domains") or [])
    selected_channels = list(status.get("selected_channels") or [])
    selected_label = ", ".join(selected_channels) if selected_channels else "none yet"
    google_status = dict(channels.get("google") or {})
    gmail_nudge = ""
    if access_identity is not None and str(access_identity.email or "").strip().lower().endswith("@gmail.com"):
        if str(google_status.get("status") or "") not in {"connected"}:
            gmail_nudge = """
            <section class="card">
              <div class="eyebrow">Fastest Real Start</div>
              <h2>You already arrived with a Gmail identity</h2>
              <p class="mini">Use Google Core first. That gives the assistant one real connected channel instead of leaving the landing as a pretty shell.</p>
              <div class="cta-row">
                <a class="cta primary" href="/setup">Connect Google Core</a>
                <a class="cta" href="/channels/google">What Google unlocks</a>
              </div>
            </section>
            """
    mode_cards = "".join(
        f"""
        <div class="signal">
          <strong>{html.escape(str(row.get('label') or 'Mode'))}</strong>
          {html.escape(str(row.get('summary') or ''))}
        </div>
        """
        for row in assistant_modes
    )
    domain_cards = "".join(
        f"""
        <section class="card">
          <div class="eyebrow">Featured Domain</div>
          <h3>{html.escape(str(row.get('label') or 'Domain'))}</h3>
          <p class="mini">{html.escape(str(row.get('summary') or ''))}</p>
          <p class="mini"><a href="{html.escape(str(row.get('href') or '#'))}">Visit domain</a></p>
        </section>
        """
        for row in featured_domains
    )
    body = f"""
    <section class="hero">
      <section class="card card-strong">
        <div class="eyebrow">Meet The Assistant</div>
        <h1>Your assistant across Gmail, Telegram, and WhatsApp.</h1>
        <p class="lead">Connect your channels, import only the history you explicitly allow, and wake up to briefs, drafts, and follow-ups that remember what matters without pretending to ingest what the adapters do not actually support.</p>
        <div class="cta-row">
          <a class="cta primary" href="/setup">Start setup</a>
          <a class="cta" href="/demo/brief">See a sample brief</a>
          <a class="cta" href="/privacy">How privacy works</a>
        </div>
        <div class="signal-grid">
          <div class="signal">
            <strong>{html.escape(str(workspace.get("mode") or "personal").replace("_", " "))}</strong>
            Workspace mode
          </div>
          <div class="signal">
            <strong>{html.escape(selected_label)}</strong>
            Selected channels
          </div>
          <div class="signal">
            <strong>{html.escape(str(workspace.get("timezone") or "unspecified"))}</strong>
            Timezone
          </div>
        </div>
      </section>
      <section class="card">
        <div class="eyebrow">Assistant Surface</div>
        <h2>What happens the moment you connect</h2>
        <div class="surface stack">
          <div><strong>Morning brief</strong><br><span class="mini">Who needs a reply, what changed overnight, and what deserves attention first.</span></div>
          <div><strong>Drafts with receipts</strong><br><span class="mini">Suggested replies keep their source trail instead of hiding why they appeared.</span></div>
          <div><strong>Follow-up memory</strong><br><span class="mini">Threads, contacts, and commitments stay principal-scoped and durable.</span></div>
          <div><strong>Channel-aware context</strong><br><span class="mini">The assistant names what it can see today and what is still staged or manual.</span></div>
        </div>
      </section>
    </section>
    {_status_header(principal_id=principal_id, access_identity=access_identity, status=status)}
    <section class="grid">
      {_status_card("Google Workspace / Gmail", dict(channels.get("google") or {}), "/channels/google")}
      {_status_card("Telegram", dict(channels.get("telegram") or {}), "/channels/telegram")}
      {_status_card("WhatsApp", dict(channels.get("whatsapp") or {}), "/channels/whatsapp")}
    </section>
    <section class="grid-2">
      <section class="card">
        <div class="eyebrow">What You Get On Day One</div>
        <h2>Real outcomes, not horizon cards</h2>
        <ul class="list">
          <li>What changed since yesterday across the channels you actually connected.</li>
          <li>Which threads need a reply or follow-up first.</li>
          <li>Drafts and action suggestions with traceable reasons.</li>
          <li>A searchable private memory seeded from explicit imports and future messages.</li>
        </ul>
      </section>
      <section class="card">
        <div class="eyebrow">Trust</div>
        <h2>What we access and what we do not fake</h2>
        <ul class="list">
          <li>{html.escape(str(storage_posture.get("source_of_truth") or "EA Postgres"))} is the source of truth for onboarding, memory, jobs, and receipts when durable storage is configured.</li>
          <li>{html.escape(str(storage_posture.get("projection_note") or ""))}</li>
          <li>{html.escape(str(storage_posture.get("attachment_note") or ""))}</li>
        </ul>
        <p class="mini"><strong>Current sample brief headline:</strong> {html.escape(str(brief_preview.get("headline") or "No brief preview yet."))}</p>
      </section>
    </section>
    {gmail_nudge}
    <section class="card">
      <div class="eyebrow">Choose Your Mode</div>
      <h2>One assistant, different working styles</h2>
      <div class="signal-grid">{mode_cards}</div>
    </section>
    {f'<section class="grid">{domain_cards}</section>' if domain_cards else ''}
    """
    return _page_shell(title="EA Assistant", body=body, current="home")


@router.get("/setup", response_class=HTMLResponse)
def setup(
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    workspace = dict(status.get("workspace") or {})
    privacy = dict(status.get("privacy") or {})
    channels = dict(status.get("channels") or {})
    selected_channels = set(status.get("selected_channels") or [])
    telegram = dict((channels.get("telegram") or {}))
    whatsapp = dict((channels.get("whatsapp") or {}))
    google = dict((channels.get("google") or {}))
    google_bundle_options = "".join(
        f"""
        <div class="surface">
          <strong>{html.escape(str(option.get('label') or option.get('bundle') or 'Google bundle'))}</strong><br>
          <span class="mini">{html.escape(str(option.get('summary') or ''))}</span>
        </div>
        """
        for option in (google.get("bundle_options") or [])[:2]
    )
    shared_fields = _shared_browser_fields(principal_id=principal_id, access_identity=access_identity, container=container)
    body = f"""
    {_status_header(principal_id=principal_id, access_identity=access_identity, status=status)}
    <section class="grid-2">
      <section class="card card-strong">
        <div class="eyebrow">Step 1</div>
        <h2>Create Workspace</h2>
        <p class="mini">Choose the assistant mode, region, language, time zone, and which channels should be staged first.</p>
        <form method="post" action="/setup/start">
          {shared_fields}
          <label for="workspace_name">Workspace name</label>
          <input id="workspace_name" name="workspace_name" value="{html.escape(str(workspace.get('name') or ''))}" required>
          <div class="split">
            <div>
              <label for="workspace_mode">Mode</label>
              <select id="workspace_mode" name="workspace_mode">
                <option value="personal"{_selected(str(workspace.get('mode') or ''), 'personal')}>Personal</option>
                <option value="team"{_selected(str(workspace.get('mode') or ''), 'team')}>Team / tenant</option>
                <option value="gm_creator_ops"{_selected(str(workspace.get('mode') or ''), 'gm_creator_ops')}>GM / creator / campaign ops</option>
              </select>
            </div>
            <div>
              <label for="timezone">Timezone</label>
              <input id="timezone" name="timezone" value="{html.escape(str(workspace.get('timezone') or ''))}" placeholder="Europe/Vienna">
            </div>
          </div>
          <div class="split">
            <div>
              <label for="region">Region</label>
              <input id="region" name="region" value="{html.escape(str(workspace.get('region') or ''))}" placeholder="AT">
            </div>
            <div>
              <label for="language">Language</label>
              <input id="language" name="language" value="{html.escape(str(workspace.get('language') or ''))}" placeholder="en">
            </div>
          </div>
          <div class="checks">
            <label class="check"><input type="checkbox" name="selected_channels" value="google"{_checked('google' in selected_channels)}> Google Workspace / Gmail</label>
            <label class="check"><input type="checkbox" name="selected_channels" value="telegram"{_checked('telegram' in selected_channels)}> Telegram</label>
            <label class="check"><input type="checkbox" name="selected_channels" value="whatsapp"{_checked('whatsapp' in selected_channels)}> WhatsApp</label>
          </div>
          <button type="submit">Save workspace</button>
        </form>
      </section>
      <section class="card">
        <div class="eyebrow">Step 2</div>
        <h2>Connect Google</h2>
        <p class="mini">Choose the smallest honest Google bundle that unlocks the assistant behavior you want today.</p>
        <p class="mini"><strong>Current status:</strong> {html.escape(str(google.get("status") or "not_selected").replace("_", " "))}</p>
        <div class="grid" style="margin-top:14px">{google_bundle_options}</div>
        <form method="post" action="/google/connect">
          {shared_fields}
          <label for="scope_bundle">Google bundle</label>
          <select id="scope_bundle" name="scope_bundle">
            <option value="core">Google Core</option>
            <option value="full_workspace">Google Full Workspace</option>
            <option value="verify">Advanced Gmail verify</option>
            <option value="send">Send only</option>
          </select>
          <button type="submit">Start Google consent</button>
        </form>
      </section>
      <section class="card">
        <div class="eyebrow">Step 3</div>
        <h2>Stage Telegram</h2>
        <p class="mini">Telegram login, bot install, and any later import path stay separate so the assistant never implies that a login widget equals full message history.</p>
        <p class="mini"><strong>Current status:</strong> {html.escape(str(telegram.get("status") or "not_selected").replace("_", " "))}</p>
        <form method="post" action="/setup/telegram">
          {shared_fields}
          <label for="telegram_ref">Telegram handle or account ref</label>
          <input id="telegram_ref" name="telegram_ref" placeholder="@username">
          <div class="split">
            <div>
              <label for="identity_mode">Identity mode</label>
              <select id="identity_mode" name="identity_mode">
                <option value="login_widget">Sign in with Telegram</option>
                <option value="oidc">Telegram OIDC</option>
              </select>
            </div>
            <div>
              <label for="history_mode">History mode</label>
              <select id="history_mode" name="history_mode">
                <option value="future_only">Future messages only</option>
                <option value="import_later">Import later</option>
                <option value="manual_forward">Manual forward / export later</option>
              </select>
            </div>
          </div>
          <div class="checks">
            <label class="check"><input type="checkbox" name="assistant_surfaces" value="dm"> DM</label>
            <label class="check"><input type="checkbox" name="assistant_surfaces" value="group"> Group</label>
            <label class="check"><input type="checkbox" name="assistant_surfaces" value="channel"> Channel</label>
          </div>
          <button type="submit">Stage Telegram lane</button>
        </form>
        <form method="post" action="/setup/telegram/link-bot">
          {shared_fields}
          <label for="bot_handle">Official bot handle</label>
          <input id="bot_handle" name="bot_handle" placeholder="@assistant_bot">
          <label for="default_chat_ref">Default chat ref</label>
          <input id="default_chat_ref" name="default_chat_ref" placeholder="chat id or handle">
          <div class="checks">
            <label class="check"><input type="checkbox" name="install_surfaces" value="dm"> Install in DM</label>
            <label class="check"><input type="checkbox" name="install_surfaces" value="group"> Install in group</label>
            <label class="check"><input type="checkbox" name="install_surfaces" value="channel"> Install in channel</label>
          </div>
          <button type="submit">Record bot install plan</button>
        </form>
      </section>
      <section class="card">
        <div class="eyebrow">Step 4</div>
        <h2>Choose WhatsApp Path</h2>
        <p class="mini">Pick either the Business onboarding path or the export-upload path. The assistant should not claim a generic WhatsApp history sync outside those routes.</p>
        <p class="mini"><strong>Current status:</strong> {html.escape(str(whatsapp.get("status") or "not_selected").replace("_", " "))}</p>
        <form method="post" action="/setup/whatsapp/business">
          {shared_fields}
          <label for="phone_number">Business phone number</label>
          <input id="phone_number" name="phone_number" placeholder="+43...">
          <label for="business_name">Business name</label>
          <input id="business_name" name="business_name" placeholder="Acme GmbH">
          <label class="check"><input type="checkbox" name="import_history_now" value="true"> Trigger history sync inside the allowed onboarding window when the adapter lands</label>
          <button type="submit">Stage business onboarding</button>
        </form>
        <form method="post" action="/setup/whatsapp/export">
          {shared_fields}
          <label for="export_label">Export label</label>
          <input id="export_label" name="export_label" placeholder="March personal export">
          <label for="selected_chat_labels_csv">Chat labels (comma separated)</label>
          <textarea id="selected_chat_labels_csv" name="selected_chat_labels_csv" placeholder="Family, Ops, Finance"></textarea>
          <label class="check"><input type="checkbox" name="include_media" value="true"> Include media references in the import plan</label>
          <button type="submit">Stage export import</button>
        </form>
      </section>
      <section class="card card-strong">
        <div class="eyebrow">Step 5</div>
        <h2>Finalize Privacy And Briefing</h2>
        <p class="mini">This sets the assistant’s retention posture and whether it may draft, suggest actions, or auto-produce briefs.</p>
        <form method="post" action="/setup/finalize">
          {shared_fields}
          <label for="retention_mode">Retention mode</label>
          <select id="retention_mode" name="retention_mode">
            <option value="full_bodies"{_selected(str(privacy.get('retention_mode') or ''), 'full_bodies')}>Keep full message bodies where allowed</option>
            <option value="metadata_first"{_selected(str(privacy.get('retention_mode') or ''), 'metadata_first')}>Metadata first</option>
            <option value="short_window"{_selected(str(privacy.get('retention_mode') or ''), 'short_window')}>Short retention window</option>
          </select>
          <div class="checks">
            <label class="check"><input type="checkbox" name="metadata_only_channels" value="telegram"{_checked('telegram' in set(privacy.get('metadata_only_channels') or []))}> Telegram metadata only</label>
            <label class="check"><input type="checkbox" name="metadata_only_channels" value="whatsapp"{_checked('whatsapp' in set(privacy.get('metadata_only_channels') or []))}> WhatsApp metadata only</label>
            <label class="check"><input type="checkbox" name="allow_drafts" value="true"{_checked(bool(privacy.get('allow_drafts')))}> Allow draft replies</label>
            <label class="check"><input type="checkbox" name="allow_action_suggestions" value="true"{_checked(bool(privacy.get('allow_action_suggestions')))}> Allow action suggestions</label>
            <label class="check"><input type="checkbox" name="allow_auto_briefs" value="true"{_checked(bool(privacy.get('allow_auto_briefs')))}> Allow automatic briefs</label>
          </div>
          <button type="submit">Build first brief preview</button>
        </form>
      </section>
    </section>
    """
    return _page_shell(title="EA Setup", body=body, current="setup")


@router.get("/privacy", response_class=HTMLResponse)
def privacy(
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    privacy_state = dict(status.get("privacy") or {})
    storage_posture = dict(status.get("storage_posture") or {})
    body = f"""
    {_status_header(principal_id=principal_id, access_identity=access_identity, status=status)}
    <section class="grid-2">
      <section class="card card-strong">
        <div class="eyebrow">Trust</div>
        <h2>What the assistant stores and where</h2>
        <ul class="list">
          <li>{html.escape(str(storage_posture.get("source_of_truth") or "EA Postgres"))} is the durable truth for onboarding state, bindings, memory, jobs, and receipts when the host is configured for durable storage.</li>
          <li>{html.escape(str(storage_posture.get("attachment_note") or "Large exports and media belong in object storage, not in the browser helper or a CRM projection."))}</li>
          <li>Channel imports stay explicit: WhatsApp export upload and Telegram history import are not implied by identity linking alone.</li>
          <li>Privacy choices here define whether the assistant keeps full bodies or metadata-only posture for selected channels.</li>
        </ul>
      </section>
      <section class="card">
        <div class="eyebrow">Current Policy</div>
        <h2>Saved briefing posture</h2>
        <p class="mini"><strong>Retention:</strong> {html.escape(str(privacy_state.get("retention_mode") or "not set"))}</p>
        <p class="mini"><strong>Metadata-only channels:</strong> {html.escape(", ".join(privacy_state.get("metadata_only_channels") or []) or "none")}</p>
        <p class="mini"><strong>Drafts allowed:</strong> {html.escape(str(bool(privacy_state.get("allow_drafts", False))).lower())}</p>
        <p class="mini"><strong>Action suggestions:</strong> {html.escape(str(bool(privacy_state.get("allow_action_suggestions", False))).lower())}</p>
        <p class="mini"><strong>Auto-briefs:</strong> {html.escape(str(bool(privacy_state.get("allow_auto_briefs", False))).lower())}</p>
      </section>
    </section>
    """
    return _page_shell(title="EA Privacy", body=body, current="privacy")


@router.get("/demo/brief", response_class=HTMLResponse)
def demo_brief(
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    preview = dict(status.get("brief_preview") or {})
    who_you_are = _render_list(preview.get("who_you_are"), fallback="No workspace profile yet.")
    connected = _render_list(preview.get("connected_channels"), fallback="No channels connected yet.")
    history_state = _render_list(preview.get("history_import_state"), fallback="No channels selected yet.")
    top_themes = _render_list(preview.get("top_themes"), fallback="No themes seeded yet.")
    top_contacts = _render_list(preview.get("top_contacts"), fallback="No contacts seeded yet.")
    first_brief = _render_list(preview.get("first_brief_preview"), fallback="Reply priorities and follow-ups will appear after setup.")
    suggested_actions = _render_list(preview.get("suggested_actions"), fallback="No suggested actions yet.")
    trust_notes = _render_list(preview.get("trust_notes"), fallback="No trust notes yet.")
    body = f"""
    {_status_header(principal_id=principal_id, access_identity=access_identity, status=status)}
    <section class="grid-2">
      <section class="card card-strong">
        <div class="eyebrow">Sample Brief</div>
        <h2>{html.escape(str(preview.get("headline") or "Your first brief will appear here after setup."))}</h2>
        <p class="mini">This is the current preview generated from the principal-scoped onboarding record, selected channels, and privacy posture.</p>
        <h3>Who you are</h3>
        <ul class="list">{who_you_are}</ul>
        <h3 style="margin-top:18px">Connected channels</h3>
        <ul class="list">{connected}</ul>
      </section>
      <section class="card">
        <div class="eyebrow">Readiness</div>
        <h2>Channel import state</h2>
        <ul class="list">{history_state}</ul>
        <h3 style="margin-top:18px">Top themes</h3>
        <ul class="list">{top_themes}</ul>
        <h3 style="margin-top:18px">Top contacts</h3>
        <ul class="list">{top_contacts}</ul>
      </section>
    </section>
    <section class="grid-2">
      <section class="card">
        <div class="eyebrow">First Morning Brief</div>
        <h2>What the assistant would summarize</h2>
        <ul class="list">{first_brief}</ul>
      </section>
      <section class="card">
        <div class="eyebrow">Suggested Actions</div>
        <h2>What to unlock next</h2>
        <ul class="list">{suggested_actions}</ul>
        <h3 style="margin-top:18px">Trust notes</h3>
        <ul class="list">{trust_notes}</ul>
      </section>
    </section>
    """
    return _page_shell(title="EA Brief Preview", body=body, current="brief")


def _channel_page(
    *,
    current: str,
    title: str,
    eyebrow: str,
    status: dict[str, object],
    detail_points: tuple[str, ...],
    body_points: tuple[str, ...],
    principal_id: str,
    access_identity: CloudflareAccessIdentity | None,
    onboarding_status: dict[str, object],
) -> HTMLResponse:
    detail_list = "".join(f"<li>{html.escape(point)}</li>" for point in detail_points)
    body_list = "".join(f"<li>{html.escape(point)}</li>" for point in body_points)
    capabilities = _render_list(status.get("capabilities"), fallback="No capabilities listed yet.")
    limitations = _render_list(status.get("limitations"), fallback="No limitations listed yet.")
    body = f"""
    {_status_header(principal_id=principal_id, access_identity=access_identity, status=onboarding_status)}
    <section class="grid-2">
      <section class="card card-strong">
        <div class="eyebrow">{html.escape(eyebrow)}</div>
        <h2>{html.escape(title)}</h2>
        <span class="pill {_status_tone(str(status.get("status") or ""))}">{html.escape(str(status.get("status") or "not_selected").replace("_", " "))}</span>
        <p class="lead" style="margin-top:16px">{html.escape(str(status.get("detail") or ""))}</p>
        <ul class="list">{detail_list}</ul>
      </section>
      <section class="card">
        <div class="eyebrow">Current contract</div>
        <h2>What EA promises here today</h2>
        <ul class="list">{body_list}</ul>
        <h3 style="margin-top:18px">Capabilities</h3>
        <ul class="list">{capabilities}</ul>
        <h3 style="margin-top:18px">Limits</h3>
        <ul class="list">{limitations}</ul>
      </section>
    </section>
    """
    return _page_shell(title=title, body=body, current=current)


@router.get("/channels/google", response_class=HTMLResponse)
def google_channel(
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _channel_page(
        current="setup",
        title="Google Workspace / Gmail",
        eyebrow="Google",
        status=dict((status.get("channels") or {}).get("google") or {}),
        detail_points=(
            "Google Core is the practical default: Gmail send and verification plus calendar and contacts read context.",
            "Google Full Workspace is the broader bundle for inbox actions and Drive file index context.",
            "Server-side OAuth stays the real path for offline use; BrowserAct is not the primary Google auth surface.",
        ),
        body_points=(
            "Connect through OAuth and keep the refresh token principal-scoped.",
            "Show the bundle choice in product language first, and only show raw scopes as expandable detail.",
            "Keep send-only, verify, core, and full-workspace as honest distinct promises.",
        ),
        principal_id=principal_id,
        access_identity=access_identity,
        onboarding_status=status,
    )


@router.get("/channels/telegram", response_class=HTMLResponse)
def telegram_channel(
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _channel_page(
        current="setup",
        title="Telegram",
        eyebrow="Telegram",
        status=dict((status.get("channels") or {}).get("telegram") or {}),
        detail_points=(
            "Identity linking and assistant-bot installation are separate decisions.",
            "Login alone does not imply generic history import.",
            "The current onboarding record can stage the lane and the bot plan while keeping that limitation explicit.",
        ),
        body_points=(
            "Record whether the assistant starts in DM, groups, or channels.",
            "Keep history import honest: future-only, import later, or manual-forward workflow.",
            "Use the official bot as the durable interaction surface once installed.",
        ),
        principal_id=principal_id,
        access_identity=access_identity,
        onboarding_status=status,
    )


@router.get("/channels/whatsapp", response_class=HTMLResponse)
def whatsapp_channel(
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> HTMLResponse:
    principal_id, status = _load_status(container=container, access_identity=access_identity)
    return _channel_page(
        current="setup",
        title="WhatsApp",
        eyebrow="WhatsApp",
        status=dict((status.get("channels") or {}).get("whatsapp") or {}),
        detail_points=(
            "Business onboarding and explicit export import are separate supported paths.",
            "The assistant should not promise generic automated history download outside those paths.",
            "The current onboarding record keeps that contract visible and durable.",
        ),
        body_points=(
            "Stage Business onboarding when the Embedded Signup adapter is ready.",
            "Use export import for personal history or unsupported cases.",
            "Keep future webhook sync and historical upload as distinct events in the onboarding story.",
        ),
        principal_id=principal_id,
        access_identity=access_identity,
        onboarding_status=status,
    )


@router.post("/setup/start")
async def setup_start(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.start_workspace(
        principal_id=principal_id,
        workspace_name=_form_value(form_data, "workspace_name", "Assistant"),
        workspace_mode=_form_value(form_data, "workspace_mode", "personal"),
        region=_form_value(form_data, "region", ""),
        language=_form_value(form_data, "language", ""),
        timezone=_form_value(form_data, "timezone", ""),
        selected_channels=_form_values(form_data, "selected_channels"),
    )
    return RedirectResponse("/setup", status_code=303)


@router.post("/setup/telegram")
async def setup_telegram(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.start_telegram(
        principal_id=principal_id,
        telegram_ref=_form_value(form_data, "telegram_ref", ""),
        identity_mode=_form_value(form_data, "identity_mode", "login_widget"),
        history_mode=_form_value(form_data, "history_mode", "future_only"),
        assistant_surfaces=_form_values(form_data, "assistant_surfaces"),
    )
    return RedirectResponse("/setup", status_code=303)


@router.post("/setup/telegram/link-bot")
async def setup_telegram_link_bot(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.link_telegram_bot(
        principal_id=principal_id,
        bot_handle=_form_value(form_data, "bot_handle", ""),
        install_surfaces=_form_values(form_data, "install_surfaces"),
        default_chat_ref=_form_value(form_data, "default_chat_ref", ""),
    )
    return RedirectResponse("/setup", status_code=303)


@router.post("/setup/whatsapp/business")
async def setup_whatsapp_business(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.start_whatsapp_business(
        principal_id=principal_id,
        phone_number=_form_value(form_data, "phone_number", ""),
        business_name=_form_value(form_data, "business_name", ""),
        import_history_now=_form_value(form_data, "import_history_now", "").lower() == "true",
    )
    return RedirectResponse("/setup", status_code=303)


@router.post("/setup/whatsapp/export")
async def setup_whatsapp_export(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    chats = tuple(
        chunk.strip()
        for chunk in _form_value(form_data, "selected_chat_labels_csv", "").split(",")
        if chunk.strip()
    )
    container.onboarding.import_whatsapp_export(
        principal_id=principal_id,
        export_label=_form_value(form_data, "export_label", ""),
        selected_chat_labels=chats,
        include_media=_form_value(form_data, "include_media", "").lower() == "true",
    )
    return RedirectResponse("/setup", status_code=303)


@router.post("/setup/finalize")
async def setup_finalize(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    container.onboarding.finalize(
        principal_id=principal_id,
        retention_mode=_form_value(form_data, "retention_mode", "full_bodies"),
        metadata_only_channels=_form_values(form_data, "metadata_only_channels"),
        allow_drafts=_form_value(form_data, "allow_drafts", "").lower() == "true",
        allow_action_suggestions=_form_value(form_data, "allow_action_suggestions", "").lower() == "true",
        allow_auto_briefs=_form_value(form_data, "allow_auto_briefs", "").lower() == "true",
    )
    return RedirectResponse("/demo/brief", status_code=303)


@router.post("/google/connect", response_model=None)
async def google_connect_browser(
    request: Request,
    container: AppContainer = Depends(get_container),
    access_identity: CloudflareAccessIdentity | None = Depends(get_cloudflare_access_identity),
) -> RedirectResponse | HTMLResponse:
    form_data = urllib.parse.parse_qs((await request.body()).decode("utf-8", errors="ignore"), keep_blank_values=True)
    principal_id = _browser_form_context(form_data=form_data, container=container, access_identity=access_identity)
    result = container.onboarding.start_google(
        principal_id=principal_id,
        scope_bundle=_form_value(form_data, "scope_bundle", "core"),
        redirect_uri_override=str(request.url_for("google_oauth_browser_callback")),
    )
    google_start = dict(result.get("google_start") or {})
    if bool(google_start.get("ready")) and str(google_start.get("auth_url") or "").strip():
        return RedirectResponse(str(google_start["auth_url"]), status_code=303)
    detail = html.escape(str(google_start.get("detail") or "Google onboarding could not start."))
    body = f"""
    <section class="card card-strong">
      <div class="eyebrow">Google Status</div>
      <h1>Google consent did not start</h1>
      <p class="lead">{detail}</p>
      <div class="cta-row">
        <a class="cta primary" href="/setup">Back to setup</a>
        <a class="cta" href="/channels/google">Google details</a>
      </div>
    </section>
    """
    return _page_shell(title="EA Google Status", body=body, current="setup")


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
    <section class="card card-strong">
      <div class="eyebrow">Google Connected</div>
      <h1>Google is now linked to this assistant</h1>
      <p class="lead">The Google binding is attached to principal <code>{html.escape(account.binding.principal_id)}</code> and can now participate in onboarding, channel-aware briefs, and smoke tests.</p>
      <div class="grid-2">
        <section class="surface">
          <h3>Connected account</h3>
          <p><strong>Email:</strong> {html.escape(account.google_email)}</p>
          <p><strong>Consent stage:</strong> {html.escape(account.consent_stage)}</p>
          <p><strong>Token status:</strong> {html.escape(account.token_status)}</p>
          <p><strong>Workspace mode:</strong> {html.escape(account.workspace_mode)}</p>
        </section>
        <section class="surface">
          <h3>Granted scopes</h3>
          <ul class="list">{scopes}</ul>
          <p class="mini" style="margin-top:14px">Next practical step: review <code>/setup</code> and run <code>POST /v1/providers/google/gmail/smoke-test</code> for the same principal when you want a live send check.</p>
        </section>
      </div>
      <div class="cta-row">
        <a class="cta primary" href="/setup">Continue setup</a>
        <a class="cta" href="/demo/brief">See sample brief</a>
      </div>
    </section>
    """
    return _page_shell(title="EA Google Connected", body=body, current="setup")
