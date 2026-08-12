# AIWriteBook export canary

This lane proves the remaining AIWriteBook runtime boundary with synthetic text.
It never uses a runner, campaign, customer, account address, or copied book text.
It is operator-run because AIWriteBook does not expose a verified public API and
its current terms prohibit unauthorized automated access.

## What the local tooling does

`scripts/materialize_aiwritebook_canary_fixture.py` creates a deterministic
Markdown source and a digest-bound manifest under
`ea/_completion/aiwritebook/canary`. This is a local operation: it does not log
in, upload, generate, spend credits, export, delete, publish, or send anything.

```sh
.venv/bin/python scripts/materialize_aiwritebook_canary_fixture.py
```

The fixture requests one Gemini chapter with no cover, translation, or
audiobook. The captured price table estimates 18 credits: 3 for the outline and
15 for writing. The operator must stop if the provider displays a higher total.

Create the non-authorizing, digest-bound approval request:

```sh
.venv/bin/python scripts/materialize_aiwritebook_canary_approval_request.py
```

This writes a mode-`0600` request and prints the only confirmation token that
can be recorded for the current manifest. It does not create an approval receipt
and does not perform a provider action.

## Approval boundary

Do not open a provider project until an authorized operator has replied with the
exact confirmation token printed by the request materializer. Approval is bound
to the generated `manifest_sha256` and explicitly covers project creation,
source upload, generation, a maximum of 18 credits, export download, and deletion
of the synthetic provider project. Publication and external send remain false.

After that exact approval is received, record it with an opaque conversation or
approval receipt reference. Do not use an email address as the reference:

```sh
.venv/bin/python scripts/record_aiwritebook_canary_approval.py \
  --confirmation '<exact token supplied by the request>' \
  --approved-by-ref '<opaque approval receipt reference>' \
  --approved-at '<UTC timestamp>'
```

The recorder rejects `continue`, `approved`, and every other reply that is not
the exact digest-bound token. Its generated JSON includes the approval request
digest and is consumed by the offline verifier; it should not be written by hand.

The resulting approval contract has this shape:

```json
{
  "contract": "ea.aiwritebook.canary_approval",
  "contract_version": 1,
  "status": "approved",
  "fixture_manifest_sha256": "<64 lowercase hex characters>",
  "approval_request_sha256": "<64 lowercase hex characters>",
  "approved_by_ref": "<opaque approval receipt reference>",
  "approved_at": "<UTC timestamp>",
  "maximum_credits": 18,
  "approved_actions": {
    "provider_project_creation": true,
    "source_upload": true,
    "generation": true,
    "credit_spend": true,
    "export_download": true,
    "provider_project_deletion": true,
    "publication": false,
    "external_send": false
  },
  "secret_material_in_receipt": false
}
```

An ordinary “continue”, “finish it”, or login confirmation is not this approval.
Do not infer permission from access to the account or from a prior Play release.

## Operator run

Use the authenticated browser manually. Confirm the provider total before
generation, record balances before and after, verify that the project is private,
review the outline and exports, and download PDF, EPUB, and DOCX. Check the PDF
visually for the marker from the manifest. Then delete only the synthetic canary
project authorized above and confirm that it is no longer accessible.

Record those observations without credentials or account addresses:

```json
{
  "contract": "ea.aiwritebook.canary_operator_observation",
  "contract_version": 1,
  "fixture_manifest_sha256": "<same manifest digest>",
  "provider_project_ref": "<opaque safe project reference>",
  "credits_before": 0,
  "credits_after": 0,
  "credits_spent": 0,
  "run_started_at": "<UTC timestamp>",
  "run_finished_at": "<UTC timestamp>",
  "automation": {
    "operator_run": true,
    "unattended_browser_automation_used": false
  },
  "privacy_ui": {
    "project_private_during_run": true,
    "shared_with_other_users": false
  },
  "cleanup": {
    "delete_requested": true,
    "project_inaccessible_after_delete": true
  },
  "human_review": {
    "outline_reviewed": true,
    "exports_reviewed": true,
    "pdf_content_marker_reviewed": true
  },
  "external_actions": {
    "publication_started": false,
    "external_send_performed": false
  }
}
```

Replace the zero balances with the observed integer values. A valid run must
show a positive deduction no greater than 18 credits.

## Offline verification

After the operator run, verify the artifacts and materialize the only receipt
that can satisfy `aiwritebook_export_roundtrip`:

```sh
.venv/bin/python scripts/verify_aiwritebook_export_roundtrip.py \
  --manifest ea/_completion/aiwritebook/canary/AIWRITEBOOK_CANARY_MANIFEST.generated.json \
  --approval ea/_completion/aiwritebook/canary/AIWRITEBOOK_CANARY_APPROVAL.generated.json \
  --observation /approved/input/aiwritebook-canary-observation.json \
  --pdf /downloaded/canary.pdf \
  --epub /downloaded/canary.epub \
  --docx /downloaded/canary.docx
```

The verifier rejects symlinks, malformed or over-budget evidence, missing human
review, unapproved external actions, unsafe archives, bad file structure, and
missing embedded markers in EPUB or DOCX. The PDF must be structurally valid and
its marker must have been reviewed by the operator because this repository does
not add a PDF text-extraction dependency merely to satisfy the canary.

The resulting receipt contains only opaque references, hashes, sizes, timestamps,
credit counts, and boolean observations. Governance validates the full contract;
a JSON file containing only `{"status":"pass"}` cannot unlock the lane.

## Completed canary evidence

The authorized human-operated canary completed on 2026-08-11. It used the
digest-bound synthetic CC0 fixture, deducted 13 credits (5,100 to 5,087) under
the approved maximum of 18, produced PDF, EPUB, and DOCX exports, and passed the
offline structural and marker checks. The project stayed private, no publication
or external send occurred, and the synthetic provider project was deleted and
confirmed inaccessible.

The sanitized durable receipt is
`config/provider_evidence/AIWRITEBOOK_EXPORT_ROUNDTRIP.source.json`. It contains
no account address, credential, source body, or secret. The generated local
receipt and downloaded exports remain private completion artifacts; governance
uses the tracked sanitized receipt as its fresh-checkout fallback. This proves
the observed canary journey, not undocumented provider backend behavior, and it
does not authorize future provider mutations or unattended automation.
