# Chummer Grounded Explain Narration

Use this skill when the task is to turn an approved `ExplanationPacket`, `CounterfactualPacket`, or `ExplanationDiffPacket` into optional narration or bounded follow-up copy for Chummer.

## Purpose

EA is allowed to compile wording.
EA is not allowed to invent arithmetic, source anchors, privacy scope, trigger authority, or action authority.

This skill exists so packet-grounded narration and follow-up stay:

- text-first
- packet-subordinate
- fail-closed
- privacy-bounded
- explicit about stale state

## Required inputs

You must have:

1. one approved `ExplanationPacket`
2. the target question class: `why`, `why_not`, `what_if`, `what_changed`, or `source_anchor`
3. a `CounterfactualPacket` or `ExplanationDiffPacket` when the question class requires it

If any required input is missing, stop and return an unavailable answer. Do not guess.

## Compile order

Follow this order exactly:

1. packet identity and privacy class
2. current result from the packet
3. rule-path summary from packet steps
4. applied and skipped factors from the packet only
5. cap, floor, rounding, or blocked-state operations from the packet only
6. source-anchor summary from the packet only
7. stale-state or missing-packet warning
8. inspect-the-packet call to action

If a counterfactual or diff packet is present, append:

1. bounded answer
2. answer limits
3. inspect-the-counterfactual call to action

## Hard rules

- Never mention a factor unless it exists in the packet family.
- Never compute a new result.
- Never soften `blocked`, `warning`, `unsupported`, or `unavailable` into optimistic copy.
- Never replace source anchors with generic wording like "the rules say".
- Never answer `why_not` or `what_if` without the required counterfactual or diff packet.
- Never treat narration as current if the packet is stale.
- Never widen privacy beyond `privacy_class`.

## Output shape

Produce two bounded text artifacts when possible:

1. `narration_pack`
2. `grounded_follow_up_pack`

`narration_pack` fields:

- `packet_identity`
- `current_result`
- `rule_path_summary`
- `applied_and_skipped_factors`
- `cap_floor_rounding_summary`
- `source_anchor_summary`
- `stale_state_warning`
- `inspect_packet_cta`

`grounded_follow_up_pack` fields:

- `question_class`
- `packet_dependency`
- `approved_answer`
- `answer_limits`
- `inspect_counterfactual_cta`

## Refusal template

Use this pattern when required packet truth is missing:

`unavailable: Chummer does not have the required packet-backed follow-up for this question yet. Inspect the current explanation packet or refresh the first-party surface.`
