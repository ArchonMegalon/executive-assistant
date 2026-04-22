# Session zero and table contract model

## Purpose

This file defines the social, safety, and playstyle agreement surface for open runs and shared-world tables.

## Canonical rule

Every open run needs a visible `TableContract`.

The contract should make expectations explicit before roster lock:

- tone
- content notes
- playstyle
- beginner-friendliness
- lethality posture
- voice, video, or text expectations
- punctuality or no-show policy
- observer and debrief policy
- rule-environment posture
- post-session reporting expectations

## Model

```yaml
table_contract:
  id: tc_shadowcasters_beginner_001
  style:
    tone:
      - noir
      - moral_pressure
    playstyle: mixed
    lethality: medium
    beginner_friendly: true
  safety:
    content_notes:
      - body_horror
      - corporate_abuse
    safety_tool_ack_required: true
  logistics:
    voice_required: true
    video_required: false
    punctuality_policy: arrive_10_minutes_early
  observer_policy:
    mode: opt_in_all_players
    fallback: manual_markers
  post_session:
    resolution_prompt_expected: true
```

## Open-run integration

The player should acknowledge the table contract before submitting the final application.

The GM should be able to see who has:

- acknowledged it
- requested clarification
- failed a required safety or logistics acknowledgement

## First proof gate

**Seattle Open Run 001**

Includes:

1. one beginner-friendly table contract
2. one content-note acknowledgement
3. one observer-policy acknowledgement
4. one visible player-facing contract summary on the run listing

Success criterion:

> The table understands what kind of run this is before scheduling and handoff happen.
