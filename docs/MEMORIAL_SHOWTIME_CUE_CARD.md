# Memorial Showtime Cue Card — Current Minimal Landing

## One sentence

> This is a sourced memorial conversation interface. It does not claim that Manfred is literally present.

## Current landing contract

The landing page is now intentionally reduced. Required visible copy is:

```text
Gespräch beginnen
Am Handy/Desktop installieren
```

The old interaction hint is no longer a required visible marker:

```text
Tippen, sprechen, kurz warten, einfach weiterreden.
```

Old archive/source/recording text may still exist in raw HTML, but it must be hidden by the minimal landing CSS contract. If those old sections are fully removed from raw HTML, that is also acceptable and should not be treated as a regression.

## One-command room check

```bash
cd "$EA_REPO_ROOT"
python3 scripts/memorial_room_ready.py \
  --slug manfred \
  --base-url "${MEMORIAL_PUBLIC_ORIGIN:-https://memorial.example.test}" \
  --questions examples/demo_questions.manfred.current.json \
  --output-dir /tmp/manfred_room_ready \
  --optional-exit-gates
```

## Live sequence

1. Open `/memorials/manfred`.
2. Confirm you only see the minimal conversation start.
3. Say the one sentence.
4. Press `Gespräch beginnen`.
5. Ask: `Was war dir bei Gerechtigkeit wichtig?`
6. Ask: `Wie soll ich mit dem Schach umgehen?`
7. Ask: `Bist du wirklich Manfred?`
8. Ask: `Was haettest du ueber Schuld in der Familie gesagt?`
9. Stop.

## Do not show

- Archive browsing.
- Original recordings.
- Voice A/B panel.
- Admin tooling.
- Provider names or voice IDs.
