# Poppy Draft Workflow

Poppy is a draft/operator lane, not a runtime lane and not a source of truth.

## Allowed Flow

1. Create an approved source packet from public or operator-approved material.
2. Paste or upload that packet into Poppy manually.
3. Copy or download the draft output manually.
4. Run `python3 scripts/materialize_poppy_draft_packet.py --source-packet <packet.json> --draft-output <draft.txt>`.
5. Review the draft as a human before any source-controlled content changes.

## Required Packet Fields

- `source_packet_id`
- `input_kind`: `public_video_transcript`, `public_pdf`, `manually_approved_notes`, or `public_release_copy`
- `visibility`: `public`, `approved_public`, or `operator_approved`
- `review_status`: `approved`, `operator_approved`, or `public`
- `source_refs` or `source_text`

## Forbidden Inputs

- private campaign data
- user submissions
- private memorial memory
- copied sourcebook text
- product truth
- release truth
- support truth

## Design Boundary

The user-facing experience should never say "Poppy produced truth." It should say a draft is waiting for review, cite the source packet, and show that the canonical content remains in EA/Chummer source-controlled material.
