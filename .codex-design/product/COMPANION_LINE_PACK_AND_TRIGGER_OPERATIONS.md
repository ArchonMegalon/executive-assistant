# Companion Line Pack and Trigger Operations

## Purpose

This file defines the content-operations system for companion, Switch, and guide-persona lines.

The companion should feel authored, localized, tested, and budgeted. It should not be one free-running model improvising over private state.

## Operating stack

```yaml
companion_content_ops:
  truth_owner: chummer6-design
  runtime_owner:
    - chummer6-ui
    - chummer6-mobile
  review_projection: Teable
  prompt_lab:
    - Prompting Systems
    - ChatPlayground AI
  validation:
    - Icanpreneur
    - MetaSurvey
    - ProductLift
  media_optional:
    - vidBoard
    - Soundmadeseen
    - Unmixr AI
  journey_proof:
    - first_party_events
    - PostHog_candidate
```

## Required registries

- `COMPANION_TRIGGER_REGISTRY.yaml`
- `COMPANION_LINE_PACK_REGISTRY.yaml`
- `COMPANION_PERSONA_AND_INTERACTION_MODEL.md`
- this operations doc

## Trigger rule

Every companion line must bind to:

- trigger id
- allowed surface
- dismissability
- annoyance budget
- locale
- privacy class
- fallback text
- owner
- review receipt

## Hard boundaries

The companion must not:

- freestyle over private campaign notes
- invent rules explanations
- hide first-party support or install paths
- use media/voice moments without opt-in
- nag after dismissal
- personalize from sensitive state without explicit consent

## Teable review queue

Teable may show:

- line candidates
- trigger mappings
- reviewer notes
- localization status
- annoyance-budget flags
- ProductLift request references

Teable edits return as AdminIntent and do not directly change runtime line packs.
