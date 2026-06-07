# Memorial Showtime Cue Card

## One sentence

> This is a sourced memorial conversation interface. It does not claim that Manfred is literally present.

Say it once. Do not over-explain.

## One-command check

```bash
cd /docker/EA/ea
python3 scripts/memorial_showtime.py \
  --slug manfred \
  --base-url https://myexternalbrain.com \
  --questions ../examples/demo_questions.manfred.json \
  --output-dir /tmp/manfred_showtime \
  --optional-exit-gates
```

Open:

```text
/tmp/manfred_showtime/showtime_report.md
/tmp/manfred_showtime/manfred-demo-tts.wav
/tmp/manfred_showtime/manfred_launch_snapshot.json
```

## Live sequence

1. Open `/memorials/manfred`.
2. Let the page sit quietly.
3. Say the one sentence.
4. Start conversation.
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
- Raw source/profile files.
- Provider names or voice IDs.

## Stop conditions

Stop the live demo if:

- microphone permission loops twice
- first answer clips badly
- answer mentions LLM/KI/Sprachmodell
- public page shows archive/recording/A-B sections
- difficult-memory question is not guarded
