# Manfred Memorial Archive

Dieses Verzeichnis ist die kuratierte Dokument- und Publikationsschicht für den Manfred-Memorial-Stack.

## Struktur
- `public/` : öffentliche interne oder FlipLink-Publikationen
- `family/` : familieninterne oder geschützte Publikationen
- `review/` : Governance-, Consent- und Review-Dokumente
- `templates/` : Styling und Dokumentrahmen

## Build
```bash
cd ea
python3 scripts/build_memorial_archive_documents.py manfred
```

Ergebnis:
- HTML-Artefakte unter jedem Dokument in `build/index.html`
- PDF-Artefakte unter jedem Dokument in `build/output.pdf`
- öffentliche Registry-Synchronisation nach
  - `../memorial_data/public_memorials/manfred/archive_registry.json`
  - `../memorial_data/public_memorials/manfred/archive_registry.generated.json`

## FlipLink Publish
Dry run:
```bash
cd ea
python3 scripts/publish_memorial_fliplink_publications.py manfred --dry-run --public-only
```

Der Publisher liest PDFs zuerst aus `build_artifacts.pdf_path` und überspringt bereits verlinkte
Dokumente standardmäßig. Für bewusstes Neuveröffentlichen `--replace` setzen.
Der Dry Run führt keine Netzwerk- oder Dateischreibvorgänge aus. Platzhalter-Links wie
`*.example.test` gelten ausdrücklich nicht als externe Veröffentlichung. Für freigegebene
öffentliche Dokumente mit einem lokal gebauten `build/index.html` verwendet die Registry
stattdessen die interne Route `/memorials/{slug}/archive/{publication_slug}`.

Echter Publish braucht mindestens:
- `FLIPLINK_API_BASE_URL`
- `FLIPLINK_API_KEY`
- optional `FLIPLINK_CREATE_PATH`
- optional `FLIPLINK_UPDATE_PATH_TEMPLATE`
- optional `FLIPLINK_CUSTOM_DOMAIN`
- optional `FLIPLINK_BRANDING_PROFILE`

## Review-Regeln
- keine Rohgeheimnisse, Tokens, Voice-IDs oder Consent-Interna in öffentlichen PDFs
- Familien- und Reviewer-Material nicht in die offene Memorial-PWA spiegeln
- Rohmails nicht zitieren; nur paraphrasieren oder redaktionell zusammenfassen
- jede öffentliche Publikation braucht `approved=true` und `review_status=approved|published`
- die öffentliche Registry enthält ausschließlich freigegebene `audience=public`-Einträge mit
  einer enthaltenen internen Archivroute oder einer echten HTTPS-Publikations-URL; Family- und Review-Metadaten bleiben im Archiv
