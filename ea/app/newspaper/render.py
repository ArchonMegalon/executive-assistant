from __future__ import annotations

import html
from typing import Any


def _story_card(s: dict[str, Any]) -> str:
    return f"""
    <article class="story-card">
      <img class="story-image" src="{html.escape(str((s.get("image") or {}).get("url") or ""))}" alt="story visual" />
      <div class="story-meta">{html.escape(str(s.get("source_label") or ""))}</div>
      <h3>{html.escape(str(s.get("headline") or ""))}</h3>
      <p class="dek">{html.escape(str(s.get("dek") or ""))}</p>
      <div class="article-body">{html.escape(str(s.get("summary") or ""))}</div>
      <p class="matters"><b>Why it matters:</b> {html.escape(str(s.get("why_it_matters") or ""))}</p>
    </article>
    """


def render_issue_html(issue: dict[str, Any]) -> str:
    sections = issue.get("sections") or {}
    must = sections.get("must_know") or []
    worth = sections.get("worth_knowing") or []
    agenda = sections.get("agenda") or []
    watch = sections.get("watchlist") or []
    signals = sections.get("signals") or []

    lead = must[0] if must else {}
    teasers = must[1:4] if len(must) > 1 else []
    pref = issue.get("preferences") or {}
    pref_prior = ", ".join((pref.get("prioritize") or [])[:8]) or "none"
    pref_avoid = ", ".join((pref.get("avoid") or [])[:8]) or "none"

    teaser_html = "".join(
        [
            f"<div class='teaser'><h4>{html.escape(str(t.get('headline') or ''))}</h4><p>{html.escape(str(t.get('dek') or ''))}</p></div>"
            for t in teasers
        ]
    ) or "<div class='teaser'><h4>No teaser</h4><p>Waiting for source updates.</p></div>"
    visual_strip = (
        "<div class='visual-strip'>"
        "<img src='https://dummyimage.com/600x338/d9e7f5/123456.png&text=Markets' alt='visual tile 1'/>"
        "<img src='https://dummyimage.com/600x338/e8f0fa/123456.png&text=Technology' alt='visual tile 2'/>"
        "</div>"
    )
    worth_html = "".join([_story_card(s) for s in worth]) or "<p class='empty'>No worth-knowing stories today.</p>"
    watch_html = "".join([_story_card(s) for s in watch]) or "<p class='empty'>No watchlist stories today.</p>"
    agenda_html = "".join(
        [
            f"<li><span>{html.escape(str(a.get('time') or ''))}</span><b>{html.escape(str(a.get('title') or ''))}</b><em>{html.escape(str(a.get('location') or ''))}</em></li>"
            for a in agenda
        ]
    ) or "<li><span></span><b>No calendar entries</b><em></em></li>"
    signal_html = "".join([f"<li>{html.escape(str(s))}</li>" for s in signals[:12]]) or "<li>No special signals.</li>"

    return f"""
    <html>
      <head>
        <meta charset="utf-8" />
      </head>
      <body class="issue">
        <header class="masthead">Tibor Daily</header>
        <div class="issue-rail">{html.escape(str(issue.get("issue_date") or ""))} | Edition {html.escape(str(issue.get("edition_no") or ""))}</div>

        <section class="page cover">
          <article class="cover-lead">
            <h1>{html.escape(str(lead.get("headline") or "No lead story"))}</h1>
            <p class="dek">{html.escape(str(lead.get("dek") or ""))}</p>
            <img class="hero" src="{html.escape(str((lead.get("image") or {}).get("url") or ""))}" />
            <p class="summary">{html.escape(str(lead.get("summary") or ""))}</p>
          </article>
          <aside class="cover-teasers">
            <h2>Inside</h2>
            {teaser_html}
            {visual_strip}
          </aside>
        </section>

        <section class="page feature-page page-break">
          <h2>Worth Knowing</h2>
          {worth_html}
        </section>

        <section class="page agenda-page page-break">
          <h2>Agenda</h2>
          <ul class="agenda-list">{agenda_html}</ul>
          <div class="pref-box"><b>Prioritize:</b> {html.escape(pref_prior)}<br/><b>Avoid:</b> {html.escape(pref_avoid)}</div>
          <h3>Signals</h3>
          <ul class="signals">{signal_html}</ul>
        </section>

        <section class="page watch-page page-break">
          <h2>Watchlist</h2>
          {watch_html}
          <footer class="footnote">{html.escape(str(issue.get("footer_note") or ""))}</footer>
        </section>
      </body>
      <style>
        @page {{
          size: A4;
          margin: 16mm 14mm 18mm 14mm;
          @bottom-right {{ content: counter(page); font: 11px Arial, sans-serif; color: #4a5a6a; }}
        }}
        body.issue {{
          margin: 0;
          color: #11161d;
          font-family: Georgia, "Times New Roman", serif;
          background: linear-gradient(180deg, #f7f9fc 0%, #ffffff 35%);
        }}
        .masthead {{ string-set: issue-title content(text); font-size: 48px; font-weight: 700; letter-spacing: .02em; margin-bottom: 4px; border-bottom: 3px solid #102030; }}
        .issue-rail {{ font: 12px/1.3 Arial, sans-serif; color: #34495e; margin-bottom: 10mm; }}
        .page {{ break-inside: avoid; }}
        .page-break {{ break-before: page; }}
        .cover {{
          display: grid;
          grid-template-columns: 2fr 1fr;
          gap: 12mm;
        }}
        .cover-lead h1 {{ margin: 0 0 6px 0; font-size: 40px; line-height: 1.08; }}
        .cover-lead .dek {{ margin: 0 0 8px 0; font: 16px/1.35 Arial, sans-serif; color: #2f4155; }}
        .hero {{ width: 100%; height: 260px; object-fit: cover; border: 1px solid #d3dce7; border-radius: 8px; }}
        .summary {{ margin-top: 8px; font: 14px/1.52 Arial, sans-serif; }}
        .cover-teasers h2 {{ margin: 0 0 8px 0; font-size: 20px; }}
        .teaser {{ border-top: 1px solid #dce5ef; padding-top: 8px; margin-top: 8px; }}
        .teaser h4 {{ margin: 0 0 3px 0; font-size: 17px; }}
        .teaser p {{ margin: 0; font: 13px/1.45 Arial, sans-serif; color: #314659; }}
        .visual-strip {{ margin-top: 10px; display: grid; grid-template-columns: 1fr; gap: 6px; }}
        .visual-strip img {{ width: 100%; height: 92px; object-fit: cover; border: 1px solid #d7e0eb; border-radius: 6px; }}
        h2 {{ margin: 0 0 8px 0; font-size: 30px; border-bottom: 1px solid #dce5ef; padding-bottom: 6px; }}
        .story-card {{ break-inside: avoid; margin-bottom: 12px; border: 1px solid #dce5ef; border-radius: 10px; padding: 10px 12px; background: #fff; }}
        .story-image {{ width: 100%; height: 210px; object-fit: cover; border-radius: 6px; border: 1px solid #d7e0eb; }}
        .story-meta {{ margin-top: 8px; font: 11px/1.2 Arial, sans-serif; letter-spacing: .06em; text-transform: uppercase; color: #5a6d81; }}
        .story-card h3 {{ margin: 4px 0; font-size: 26px; line-height: 1.2; }}
        .story-card .dek {{ margin: 0 0 6px 0; font: 13px/1.4 Arial, sans-serif; color: #34495e; }}
        .article-body {{ column-count: 2; column-gap: 8mm; column-fill: balance; font: 13px/1.48 Arial, sans-serif; color: #1d2733; }}
        .matters {{ margin: 8px 0 0 0; font: 12px/1.35 Arial, sans-serif; color: #24374a; }}
        .agenda-list {{ list-style: none; padding: 0; margin: 0 0 10px 0; }}
        .agenda-list li {{ display: grid; grid-template-columns: 150px 1fr; gap: 8px; border-top: 1px solid #dce5ef; padding: 8px 0; font: 13px/1.4 Arial, sans-serif; }}
        .agenda-list li em {{ grid-column: 2; color: #4a5a6a; font-style: normal; }}
        .pref-box {{ border: 1px solid #dce5ef; border-radius: 8px; padding: 8px 10px; margin: 8px 0 12px 0; font: 12px/1.5 Arial, sans-serif; background: #f9fbff; }}
        .signals {{ margin: 0; padding-left: 18px; font: 13px/1.45 Arial, sans-serif; }}
        .footnote {{ margin-top: 10px; font: 11px/1.3 Arial, sans-serif; color: #5a6d81; }}
        .empty {{ font: 13px/1.5 Arial, sans-serif; color: #52667a; }}
      </style>
    </html>
    """
