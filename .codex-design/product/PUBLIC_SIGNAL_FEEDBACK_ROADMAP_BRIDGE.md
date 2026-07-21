# Public signal feedback, roadmap, and changelog bridge

## Status

Accepted design posture; implementation remains gated by Chummer-owned routes, adapters, closeout evidence, and validators.

## Purpose

The public signal board is the public feedback, voting, roadmap-projection, changelog-projection, and voter-closeout surface for Chummer.

It gives users a visible place to suggest, vote, follow public direction, and get notified when user-requested work ships. It does not become roadmap truth, support truth, release truth, or product priority.

## Authority rule

Hosted public signal mirrors may collect and project public demand. They must not decide product direction.

Accepted truth still flows through:

```text
Public signal posts / votes / comments
  -> EA synthesis
  -> Product Governor decision
  -> chummer6-design canonical patch or milestone
  -> implementation / release / public guide proof
  -> hosted roadmap, changelog, and voter closeout projection
```

## Ownership

- `chummer6-hub` owns public surface integration, fallback routes, moderation hooks, and user-facing route behavior.
- `chummer6-design` owns public signal policy, taxonomy, status mapping, and truth boundaries.
- `fleet` owns digest and closeout evidence synthesis after Hub-owned intake exists.
- Product Governor owns priority posture, status-change approval, stale planned item review, and public-promise drift escalation.

## Allowed uses

- Public feature ideas.
- Voting and public comments.
- Public roadmap projection.
- Public changelog projection.
- Voter notification when requested work ships.
- Public demand collection for Build & Explain, KARMA FORGE, BLACK LEDGER, Community Hub, Mobile Companion, creator publishing, and guide/help clarity.
- Weekly public signal digest input for EA and the Product Governor.

## Forbidden uses

- Support tickets or private support threads.
- Crash reports, logs, account issues, install failures, or private bugs.
- Canonical roadmap truth.
- Implementation priority.
- Release truth.
- Rules truth.
- Campaign, table, roster, or world truth.
- Private campaign spoilers, private logs, account data, or copyrighted source text.

## Public routes

- `/feedback` projects public ideas, votes, comments, categories, and support-boundary copy.
- `/roadmap` projects selected public direction from Chummer-owned planning and milestone truth.
- `/changelog` projects shipped updates and voter-closeout notices backed by Chummer-owned release or public availability proof.

Every route must retain a first-party fallback path. Hosted signal outage or misconfiguration must degrade to Chummer-owned help, status, and release surfaces rather than hiding the path.

## Status mapping

Public signal statuses are public approximations. Internal truth remains in `chummer6-design`, milestone registries, release registries, Hub support/case state, Fleet pulse packets, and closeout packets.

| Public signal status | Internal meaning | Evidence required |
| --- | --- | --- |
| `new` | unreviewed public signal | public post receipt |
| `needs_clarification` | routed to follow-up | structured intake, guided follow-up, survey follow-up, scheduling handoff, or owner follow-up packet |
| `under_review` | EA or Product Governor triage | digest row or triage record |
| `researching` | routed to discovery lane | discovery packet owner and route |
| `planned` | accepted into design or milestone | design doc, milestone registry entry, horizon update, or accepted Product Governor decision packet |
| `in_progress` | implementation has owner | repo/milestone owner evidence |
| `shipped` | user-available with closeout | release, guide, Hub route, artifact proof, and closeout packet |
| `declined` | rejected with reason | public-safe reason |
| `duplicate` | merged or clustered | merge target or cluster id |

“Planned” must not mean “someone liked it.” “Shipped” must not mean “PR merged” unless the feature is actually available to users.

## Support misroutes

The public signal board is public. Posts that contain support, private, crash, install, account, or spoiler material must be handled explicitly:

```yaml
support_misroute_policy:
  examples:
    - crash report on the public board
    - install problem on the public board
    - account issue on the public board
    - private campaign bug on the public board
  action:
    - hide_or_mark_not_public_if_sensitive
    - reply_with_first_party_support_path
    - create_internal_support_routing_receipt_if_possible
    - do_not_treat_as_feature_vote
```

Required public warning:

> Do not post private logs, account data, campaign spoilers, copyrighted source text, or private table details. For crashes, bugs, install problems, account issues, or private support, use Chummer Help.

## Weekly digest

EA prepares a weekly public signal digest for Product Governor review:

- new high-vote ideas
- duplicate clusters
- support misroutes
- public guide/help gaps
- horizon demand
- categories with noisy taxonomy
- stale planned items
- shipped candidates needing closeout evidence

EA may normalize, deduplicate, and cluster public signals. It must not convert votes into implementation priority automatically.

## Closeout rule

For any public signal item marked `shipped`:

- closeout packet exists
- release, public guide, Hub route, or artifact proof exists
- voter notification allowed flag is set
- public changelog entry exists or an explicit reason says why not
- support, install, release, and roadmap surfaces do not contradict the shipped claim

## First board set

Initial public signal boards:

- Desktop Preview
- Build & Explain
- KARMA FORGE
- BLACK LEDGER
- Community Hub
- Mobile Companion
- Creator Publishing
- Guide and Help

## Success criteria

The bridge is working when users can see and vote on public ideas, high-signal ideas become governed discovery packets, voters are notified when their requested feature ships, the hosted projection does not contradict the design roadmap, support misroutes decrease, and every public “shipped” claim has closeout evidence.
