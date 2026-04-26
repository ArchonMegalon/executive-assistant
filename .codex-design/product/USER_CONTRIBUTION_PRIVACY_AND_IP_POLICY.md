# User Contribution Privacy and IP Policy

## Purpose

This file defines the product boundary for user-submitted intel, house rules, run reports, session transcripts, feedback, creator material, and public content suggestions.

Chummer can make user worlds feel alive without becoming a leak machine.

## Core rules

- Do not capture raw sourcebook text as contribution data.
- Do not publish private campaign spoilers by default.
- Do not analyze sessions without consent.
- Do not turn session-analysis tools into player scoring.
- Do not let external tools retain more payload than the workflow needs.
- Do not use public feedback tools for private support or account issues.
- Do not send newsletters or digests without the proper consent or transactional basis.
- Do not expose faction-secret state through Teable, Signitic, Emailit, ProductLift, or public pages.

## Contribution classes

```yaml
contribution_classes:
  public_feedback:
    tools:
      - ProductLift
      - MetaSurvey
    raw_retention: short
    public_by_default: true
  intel_report:
    tools:
      - Deftform
      - FacePop
      - Teable
    raw_retention: review_window
    public_by_default: false
  house_rule_request:
    tools:
      - Deftform
      - Icanpreneur
      - MetaSurvey
      - Teable
    raw_retention: summarize_after_decision
    public_by_default: false
  session_debrief:
    tools:
      - Hedy
      - Nonverbia
      - Unmixr AI
    raw_retention: minimal_and_consent_bound
    public_by_default: false
  creator_submission:
    tools:
      - Deftform
      - Teable
      - MarkupGo
      - vidBoard
    raw_retention: project_bound
    public_by_default: false
```

## Public-safe summarization

Before any contribution becomes public:

- remove private names unless explicitly approved
- remove private table notes
- remove account/support details
- remove raw copyrighted text
- label spoiler class
- label faction-secret class
- keep a source receipt and reviewer receipt

## Deletion and retirement

Every contribution class must define:

- who can request deletion
- what can be deleted
- what must be retained as a receipt
- when raw payload is summarized
- when public artifacts are retired or superseded
