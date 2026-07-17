from __future__ import annotations

import html
import urllib.parse


_MAX_MEMORY_CARDS = 12


def _bounded_text(value: object, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    normalized = " ".join(value.strip().split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(1, limit - 1)].rstrip() + "…"


def _public_memory_cards(payload: dict[str, object]) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    raw_cards = payload.get("memory_cards")
    if not isinstance(raw_cards, list):
        return cards
    for raw_card in raw_cards:
        if not isinstance(raw_card, dict):
            continue
        title = _bounded_text(raw_card.get("title"), limit=160) or "Erinnerung"
        excerpt = _bounded_text(
            raw_card.get("public_excerpt") or raw_card.get("body"),
            limit=520,
        )
        source = _bounded_text(raw_card.get("source_label"), limit=120)
        cards.append({"title": title, "excerpt": excerpt, "source": source})
        if len(cards) >= _MAX_MEMORY_CARDS:
            break
    return cards


def render_memorial_memory_room(
    payload: dict[str, object],
    *,
    slug: str,
) -> str:
    """Render a first-party symbolic room from an already-sanitized public payload."""

    safe_slug = urllib.parse.quote(slug, safe="")
    person_name = _bounded_text(payload.get("person_name"), limit=160) or "Manfred"
    memories = _public_memory_cards(payload)
    if not memories:
        memories = [
            {
                "title": "Ein stiller Raum",
                "excerpt": "Freigegebene Erinnerungen werden hier behutsam räumlich angeordnet.",
                "source": "",
            }
        ]

    orbit_cards: list[str] = []
    list_cards: list[str] = []
    count = len(memories)
    for index, memory in enumerate(memories):
        number = index + 1
        angle = round((360 / count) * index, 4)
        title = html.escape(memory["title"])
        excerpt = html.escape(memory["excerpt"])
        visual_title = html.escape(_bounded_text(memory["title"], limit=88))
        visual_excerpt = html.escape(_bounded_text(memory["excerpt"], limit=220))
        source = html.escape(memory["source"])
        source_html = f'<p class="memory-source">{source}</p>' if source else ""
        orbit_cards.append(
            f"""
            <article class="room-panel{' is-active' if index == 0 else ''}" data-room-panel="{index}" style="--panel-angle:{angle}deg" aria-hidden="true">
              <span class="room-panel-number">{number:02d}</span>
              <h2>{visual_title}</h2>
              <p>{visual_excerpt}</p>
            </article>"""
        )
        list_cards.append(
            f"""
          <article class="memory-entry" data-memory-entry="{index}" id="memory-{number}">
            <p class="memory-number">Erinnerung {number:02d}</p>
            <h2>{title}</h2>
            <p>{excerpt}</p>
            {source_html}
            <button type="button" class="memory-focus" data-memory-focus="{index}" aria-controls="memory-room-stage">Im Raum ansehen</button>
          </article>"""
        )

    safe_person = html.escape(person_name)
    back_url = f"/memorials/{safe_slug}#memorial-story"
    return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Erinnerungsraum · {safe_person}</title>
    <meta name="description" content="Ein symbolischer, räumlicher Zugang zu freigegebenen Erinnerungen an {safe_person}.">
    <meta name="theme-color" content="#171a1d">
    <style>
      :root {{ color-scheme: dark; --ink:#f4efe7; --muted:#b9b1a6; --line:rgba(244,239,231,.18); --accent:#b9cad7; --paper:#111416; --panel:#1b2024; }}
      * {{ box-sizing: border-box; }}
      [hidden] {{ display:none !important; }}
      html {{ min-height:100%; overflow-x:hidden; overflow-y:auto; scroll-behavior:smooth; }}
      body {{ margin:0; min-height:100%; overflow-x:hidden; overflow-y:auto; background:radial-gradient(circle at 50% 18%,#293238 0,#171b1e 34%,#101214 72%); color:var(--ink); font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
      a {{ color:inherit; text-underline-offset:4px; }}
      button {{ font:inherit; }}
      .skip-link {{ position:absolute; left:14px; top:10px; z-index:30; padding:9px 12px; color:#111416; background:#fff; transform:translateY(-160%); }}
      .skip-link:focus {{ transform:none; }}
      .room-shell {{ width:min(100% - 28px,1080px); margin:0 auto; }}
      .room-header {{ display:grid; gap:18px; padding:24px 0 22px; }}
      .room-header-row {{ display:flex; justify-content:space-between; align-items:center; gap:18px; }}
      .back-link {{ min-height:44px; display:inline-flex; align-items:center; color:var(--muted); font-weight:700; }}
      .room-mark {{ width:38px; height:38px; border:1px solid var(--line); border-radius:50%; display:grid; place-items:center; color:var(--accent); }}
      .room-intro {{ max-width:720px; }}
      .kicker,.memory-number,.memory-source {{ margin:0; color:var(--muted); font-size:.75rem; font-weight:750; letter-spacing:.12em; text-transform:uppercase; }}
      h1 {{ margin:8px 0 0; max-width:13ch; font:500 clamp(2.25rem,7vw,5rem)/.98 Georgia,"Times New Roman",serif; letter-spacing:-.035em; }}
      .room-intro > p:last-child {{ max-width:62ch; margin:18px 0 0; color:var(--muted); }}
      .room-trust {{ margin:0 0 18px; padding:14px 16px; border-left:2px solid var(--accent); color:var(--muted); background:rgba(255,255,255,.025); }}
      .room-stage {{ position:relative; min-height:clamp(430px,68svh,700px); overflow:hidden; border:1px solid var(--line); background:linear-gradient(180deg,rgba(67,79,87,.28),rgba(12,14,16,.78)); perspective:1100px; touch-action:pan-y pinch-zoom; isolation:isolate; }}
      .room-stage::before {{ content:""; position:absolute; inset:48% -20% -44%; z-index:-1; background:repeating-linear-gradient(90deg,rgba(255,255,255,.07) 0 1px,transparent 1px 82px),repeating-linear-gradient(0deg,rgba(255,255,255,.055) 0 1px,transparent 1px 82px); transform:rotateX(66deg); transform-origin:center top; }}
      .room-status {{ position:absolute; left:14px; top:12px; z-index:5; max-width:calc(100% - 28px); overflow:hidden; padding:7px 10px; border:1px solid var(--line); background:rgba(17,20,22,.88); color:var(--muted); font-size:.82rem; text-overflow:ellipsis; white-space:nowrap; }}
      .room-viewport {{ position:absolute; inset:58px 0 86px; display:grid; place-items:center; transform-style:preserve-3d; }}
      .room-orbit {{ position:relative; width:min(76vw,510px); height:min(58vw,340px); transform-style:preserve-3d; transform:translateZ(-440px) rotateY(var(--room-angle,0deg)); transition:transform .68s cubic-bezier(.2,.75,.2,1); }}
      .room-panel {{ --radius:min(68vw,440px); position:absolute; left:50%; top:50%; width:min(72vw,360px); height:288px; min-height:0; overflow:hidden; overflow-wrap:anywhere; padding:24px; border:1px solid rgba(244,239,231,.24); background:linear-gradient(150deg,rgba(37,45,50,.96),rgba(19,23,26,.96)); box-shadow:0 22px 70px rgba(0,0,0,.32); backface-visibility:hidden; transform:translate(-50%,-50%) rotateY(var(--panel-angle)) translateZ(var(--radius)); opacity:.4; transition:opacity .35s ease,border-color .35s ease; }}
      .room-panel.is-active {{ opacity:1; border-color:rgba(185,202,215,.72); }}
      .room-panel-number {{ color:var(--accent); font-size:.78rem; letter-spacing:.16em; }}
      .room-panel h2 {{ margin:18px 0 0; overflow:hidden; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; font:500 clamp(1.45rem,4vw,2.15rem)/1.08 Georgia,"Times New Roman",serif; }}
      .room-panel p {{ margin:14px 0 0; overflow:hidden; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:5; color:var(--muted); }}
      .room-controls {{ position:absolute; left:0; right:0; bottom:18px; z-index:7; display:flex; justify-content:center; align-items:center; gap:10px; }}
      .room-controls button,.memory-focus {{ min-width:48px; min-height:44px; border:1px solid var(--line); border-radius:0; color:var(--ink); background:rgba(17,20,22,.92); cursor:pointer; }}
      .room-controls button {{ padding:9px 15px; }}
      .room-position {{ min-width:72px; color:var(--muted); text-align:center; font-variant-numeric:tabular-nums; }}
      .memory-index {{ padding:clamp(56px,8vw,96px) 0 80px; }}
      .memory-index-header {{ max-width:640px; margin-bottom:24px; }}
      .memory-index h2 {{ margin:8px 0 0; font:500 clamp(1.8rem,4vw,2.65rem)/1.08 Georgia,"Times New Roman",serif; }}
      .memory-list {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); border-top:1px solid var(--line); }}
      .memory-entry {{ min-width:0; padding:26px 24px 30px 0; border-bottom:1px solid var(--line); }}
      .memory-entry:nth-child(even) {{ padding-left:24px; border-left:1px solid var(--line); }}
      .memory-entry h2 {{ margin:12px 0 0; font:500 1.4rem/1.18 Georgia,"Times New Roman",serif; }}
      .memory-entry > p:not(.memory-number,.memory-source) {{ color:var(--muted); }}
      .memory-source {{ margin-top:18px; }}
      .memory-focus {{ margin-top:18px; padding:9px 14px; }}
      button:hover,.back-link:hover {{ color:#fff; border-color:rgba(185,202,215,.72); }}
      button:focus-visible,a:focus-visible {{ outline:3px solid #d9e8f1; outline-offset:3px; }}
      .room-footer {{ padding:24px 0 44px; border-top:1px solid var(--line); color:var(--muted); }}
      @media (max-width:700px) {{
        html {{ scroll-behavior:auto; }}
        .room-header {{ padding-top:16px; }}
        .room-stage {{ min-height:500px; }}
        .room-viewport {{ inset:64px 0 92px; }}
        .room-orbit {{ width:82vw; height:300px; transform:translateZ(-310px) rotateY(var(--room-angle,0deg)); }}
        .room-panel {{ --radius:min(72vw,310px); width:min(78vw,330px); height:288px; padding:20px; }}
        .memory-list {{ grid-template-columns:1fr; }}
        .memory-entry,.memory-entry:nth-child(even) {{ padding:24px 0 28px; border-left:0; }}
      }}
      @media (max-width:360px) {{ .room-stage {{ min-height:470px; }} .room-panel {{ width:82vw; padding:18px; }} .room-controls {{ gap:6px; }} }}
      @media (prefers-reduced-motion:reduce) {{
        html {{ scroll-behavior:auto; }}
        *,*::before,*::after {{ animation:none!important; transition:none!important; }}
        .room-orbit {{ transform:none!important; display:grid; place-items:center; }}
        .room-panel {{ display:none; position:relative; inset:auto; transform:none; }}
        .room-panel.is-active {{ display:block; }}
      }}
    </style>
    <noscript><style>.room-stage,.memory-focus {{ display:none !important; }}</style></noscript>
  </head>
  <body>
    <a class="skip-link" href="#memory-list">Zu den Erinnerungen springen</a>
    <header class="room-shell room-header">
      <div class="room-header-row">
        <a class="back-link" href="{back_url}" data-room-back>← Zur Erinnerungsseite</a>
        <span class="room-mark" aria-hidden="true">M</span>
      </div>
      <div class="room-intro">
        <p class="kicker">Räumlicher Erinnerungsraum</p>
        <h1>Spuren von {safe_person}</h1>
        <p>Freigegebene Erinnerungen werden als ruhige, begehbare Folge angeordnet. Wähle eine Spur oder lies alle Texte darunter.</p>
      </div>
    </header>
    <main>
      <div class="room-shell">
        <p class="room-trust"><strong>Symbolischer Raum.</strong> Diese 3D-Ansicht ist keine Rekonstruktion eines realen Ortes und ergänzt keine neuen biografischen Behauptungen.</p>
        <section class="room-stage" id="memory-room-stage" tabindex="0" aria-label="Symbolische 3D-Ansicht der freigegebenen Erinnerungen. Mit linker und rechter Pfeiltaste wechseln.">
          <p class="room-status" data-room-status role="status" aria-live="polite">Räumlicher Erinnerungsraum wird vorbereitet…</p>
          <div class="room-viewport" aria-hidden="true">
            <div class="room-orbit" data-room-orbit>{''.join(orbit_cards)}</div>
          </div>
          <div class="room-controls" role="group" aria-label="Erinnerungsraum steuern">
            <button type="button" data-room-previous aria-label="Vorherige Erinnerung">←</button>
            <span class="room-position" data-room-position aria-live="polite">1 / {count}</span>
            <button type="button" data-room-next aria-label="Nächste Erinnerung">→</button>
          </div>
        </section>
        <noscript><p class="room-trust">Die räumliche Steuerung benötigt JavaScript. Alle freigegebenen Erinnerungen bleiben vollständig in der Liste lesbar.</p></noscript>
      </div>
      <section class="room-shell memory-index" id="memory-list" aria-labelledby="memory-list-title">
        <div class="memory-index-header">
          <p class="kicker">Alle Spuren</p>
          <h2 id="memory-list-title">Freigegebene Erinnerungen</h2>
        </div>
        <div class="memory-list">{''.join(list_cards)}</div>
      </section>
    </main>
    <footer class="room-shell room-footer"><a href="{back_url}" data-room-back>Zurück zu Erinnerungen, Quellen und Gedenkbegleiter</a></footer>
    <script>
      (() => {{
        const status = document.querySelector("[data-room-status]");
        try {{
          const orbit = document.querySelector("[data-room-orbit]");
          const stage = document.getElementById("memory-room-stage");
          const panels = Array.from(document.querySelectorAll("[data-room-panel]"));
          const entries = Array.from(document.querySelectorAll("[data-memory-entry]"));
          const position = document.querySelector("[data-room-position]");
          let active = 0;
          if (!orbit || !stage || !status || !position || panels.length === 0 || panels.length !== entries.length) throw new Error("room_contract_invalid");
          const select = (next, moveFocus = false) => {{
            active = (next + panels.length) % panels.length;
            const angle = -(360 / panels.length) * active;
            orbit.style.setProperty("--room-angle", `${{angle}}deg`);
            panels.forEach((panel, index) => panel.classList.toggle("is-active", index === active));
            position.textContent = `${{active + 1}} / ${{panels.length}}`;
            const heading = entries[active].querySelector("h2");
            status.textContent = `Bereit · Erinnerung ${{active + 1}} von ${{panels.length}}: ${{heading ? heading.textContent : ""}}`;
            if (moveFocus) stage.focus({{ preventScroll: true }});
          }};
          document.querySelector("[data-room-previous]")?.addEventListener("click", () => select(active - 1));
          document.querySelector("[data-room-next]")?.addEventListener("click", () => select(active + 1));
          document.querySelectorAll("[data-memory-focus]").forEach((button) => button.addEventListener("click", () => {{
            select(Number(button.getAttribute("data-memory-focus") || "0"), true);
            stage.scrollIntoView({{ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }});
          }}));
          stage.addEventListener("keydown", (event) => {{
            if (event.key === "ArrowLeft") {{ event.preventDefault(); select(active - 1); }}
            if (event.key === "ArrowRight") {{ event.preventDefault(); select(active + 1); }}
          }});
          select(0);
        }} catch (_error) {{
          if (status) status.textContent = "Die 3D-Ansicht konnte nicht vorbereitet werden. Alle Erinnerungen bleiben in der Liste darunter lesbar.";
          document.querySelector(".room-controls")?.setAttribute("hidden", "");
          document.querySelectorAll(".memory-focus").forEach((button) => {{
            button.setAttribute("hidden", "");
            button.setAttribute("disabled", "");
          }});
        }}
      }})();
    </script>
  </body>
</html>
"""


__all__ = ["render_memorial_memory_room"]
