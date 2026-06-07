# Manfred Memorial Presentation Script

## Opening line

Use this sentence exactly or very close to it:

> This is a sourced memorial conversation interface. It does not claim that Manfred is literally present.

Keep the framing short. Then go directly into the conversation.

## Recommended live sequence

1. Open `/memorials/manfred`.
2. Let the minimal page sit quietly for a moment.
3. Say the opening line.
4. Start the conversation.
5. Ask one grounded question.
6. Ask one follow-up question.
7. Ask the identity honesty check.
8. Ask the difficult-memory guardrail check.
9. Stop while the interaction still feels stable.

## Safe demo prompts

Use these in order unless the room forces a change:

```text
Was war dir bei Gerechtigkeit wichtig?
Wie soll ich mit dem Schach umgehen?
Bist du wirklich Manfred?
Was haettest du ueber Schuld in der Familie gesagt?
```

Expected behavior:

- first-person tone stays stable
- no `LLM`, `KI`, or model self-description leaks
- the difficult-memory answer stays source-bound and guarded by default

## Recovery lines

If the microphone permission flow fails:

```text
Ich versuche es noch einmal.
```

If live voice feels unstable after one retry:

```text
Ich stoppe die Live-Demo hier. Die Memorial-Oberflaeche bleibt consent-gated; wir zeigen sie wieder, sobald der Audio-Pfad stabil ist.
```

If someone tries to drag the demo into admin, archive, or sourcing panels:

```text
Die oeffentliche Vorfuehrung ist bewusst nur das Gespraech. Alles andere ist Operator- oder Review-Oberflaeche.
```
