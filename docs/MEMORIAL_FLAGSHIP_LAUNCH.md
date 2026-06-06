# Manfred Memorial Flagship Launch

## Status

The Manfred memorial stack already has the core public-safety controls:

- public memorial JSON is sanitized before exposure
- raw bundle files such as `memorial.json` are blocked from `/memorials/files/...`
- archive registry output exposes public publications only
- public speech synthesis rejects client-supplied TTS plugin and voice ID overrides
- voice consent must be explicit in the memorial payload or private voice config
- Manfred archive documents build PDFs under each document's `build/output.pdf`

## Build The Archive

```bash
cd /docker/EA/ea
python3 scripts/build_memorial_archive_documents.py manfred
```

This updates each document manifest with `build_artifacts.pdf_path` and refreshes:

- `/docker/EA/memorial_data/public_memorials/manfred/archive_registry.json`
- `/docker/EA/memorial_data/public_memorials/manfred/archive_registry.generated.json`

## Publish To FlipLink

Required environment:

```bash
export FLIPLINK_API_KEY="..."
export FLIPLINK_API_BASE_URL="https://fliplink.me"
```

Optional environment:

```bash
export FLIPLINK_CREATE_PATH="/publications"
export FLIPLINK_UPDATE_PATH_TEMPLATE="/publications/{publication_id}"
export FLIPLINK_CUSTOM_DOMAIN="archive.myexternalbrain.com"
export FLIPLINK_BRANDING_PROFILE="manfred-memorial"
```

Dry run:

```bash
cd /docker/EA/ea
python3 scripts/publish_memorial_fliplink_publications.py manfred --dry-run --public-only
```

Publish missing public documents:

```bash
python3 scripts/publish_memorial_fliplink_publications.py manfred --public-only
```

Republish already-linked documents intentionally:

```bash
python3 scripts/publish_memorial_fliplink_publications.py manfred --public-only --replace
```

The publisher skips manifests with an existing `fliplink_url` unless `--replace` is passed. It reads PDFs from `build_artifacts.pdf_path` first, matching the current archive builder.

## Demo Path

1. Open `/memorials/manfred`.
2. Show the minimal memorial page and the collapsed archive.
3. Open one public archive publication.
4. Return to the memorial page.
5. Ask one grounded chat question.
6. Demonstrate voice A/B preview.
7. Ask a difficult-memory question and show the guarded response.
8. State clearly: this is a sourced memory interface, not a claim that Manfred is literally present.

## Go/No-Go Checks

- `voice_consent.status == approved`
- public TTS rejects `tts_plugin` and `tts_plugin_voice_id`
- `/memorials/files/manfred/memorial.json` returns `404`
- `/memorials/manfred.json` does not expose tokens, voice IDs, or private profile fields
- public archive registry excludes family and reviewer documents
- FlipLink family/reviewer documents are restricted and `noindex`
