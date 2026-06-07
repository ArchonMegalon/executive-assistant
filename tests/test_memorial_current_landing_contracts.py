from __future__ import annotations


def test_current_minimal_landing_accepts_hidden_old_sections(monkeypatch):
    import scripts.memorial_demo_rehearsal as rehearsal

    html = """
    <html><head><style>
      .hero-copy > h1,
      #memorial-interaction-hint,
      footer {
        display: none !important;
      }
    </style></head>
    <body>
      <button>Gespräch beginnen</button>
      <p>Am Handy/Desktop installieren</p>
      <img src="/memorials/manfred/icon-180.png">
      <section>Originalaufnahmen</section>
      <section>Belegte Erinnerungen</section>
      <section>Archiv lesen</section>
    </body></html>
    """

    def fake_request(*args, **kwargs):
        return 200, {"cache-control": "no-store"}, html.encode("utf-8")

    monkeypatch.setattr(rehearsal, "request", fake_request)
    report = rehearsal.RehearsalReport(slug="manfred", base_url="https://example.test")

    rehearsal.check_landing(report, base="https://example.test", slug="manfred")

    assert not report.failed
    assert any(item.code == "landing_minimal_css_present" and item.status == "pass" for item in report.checks)
    assert any(item.code == "old_section_marker_hidden_not_removed" and item.status == "warn" for item in report.checks)


def test_current_minimal_landing_accepts_removed_old_sections_without_css(monkeypatch):
    import scripts.memorial_demo_rehearsal as rehearsal

    html = """
    <html><body>
      <button>Gespräch beginnen</button>
      <p>Am Handy/Desktop installieren</p>
      <img src="/memorials/manfred/icon-180.png">
    </body></html>
    """

    def fake_request(*args, **kwargs):
        return 200, {"cache-control": "no-store"}, html.encode("utf-8")

    monkeypatch.setattr(rehearsal, "request", fake_request)
    report = rehearsal.RehearsalReport(slug="manfred", base_url="https://example.test")

    rehearsal.check_landing(report, base="https://example.test", slug="manfred")

    assert not report.failed
    assert any(item.code == "landing_minimal_source_removed" and item.status == "pass" for item in report.checks)


def test_current_minimal_landing_fails_without_css_when_old_sections_remain(monkeypatch):
    import scripts.memorial_demo_rehearsal as rehearsal

    html = """
    <html><body>
      <button>Gespräch beginnen</button>
      <p>Am Handy/Desktop installieren</p>
      <img src="/memorials/manfred/icon-180.png">
      <section>Originalaufnahmen</section>
    </body></html>
    """

    def fake_request(*args, **kwargs):
        return 200, {"cache-control": "no-store"}, html.encode("utf-8")

    monkeypatch.setattr(rehearsal, "request", fake_request)
    report = rehearsal.RehearsalReport(slug="manfred", base_url="https://example.test")

    rehearsal.check_landing(report, base="https://example.test", slug="manfred")

    assert report.failed
    assert any(item.code == "landing_minimal_css_missing" and item.status == "fail" for item in report.checks)
