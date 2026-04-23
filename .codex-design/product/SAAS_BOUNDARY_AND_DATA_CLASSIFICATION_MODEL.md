# SaaS Boundary and Data Classification Model

This EA-local product note defines the shared boundary for external SaaS tools used around Chummer product, media, docs, feedback, and support workflows.

## Hard Boundary

No SaaS writes canon.
No SaaS generates implementation tasks directly.

External tools may produce drafts, render assets, summarize feedback, or check readability, but Chummer-owned review and receipt paths decide whether anything becomes a product claim, queue item, public status, release gate, or shipped artifact.

## Data Classes

* `public`: already-approved public copy, guides, media briefs, release notes, public feature entries, and public roadmap summaries.
* `internal_product`: non-secret design drafts, triage notes, release planning, and support trend summaries.
* `campaign_private`: table state, player notes, character details, unreleased run content, private feedback, and support case specifics.
* `credential_bearing`: API keys, passwords, OAuth tokens, cookies, session exports, and account recovery material.

## Tool Rules

* Public and internal product data may be sent to approved SaaS tools only when the workflow has an owner and a receipt.
* `campaign_private` data stays out of public SaaS surfaces unless an explicit export policy and user action allow it.
* `credential_bearing` data is never sent to these tools.
* Every SaaS-backed workflow must preserve the Chummer-owned source, reviewer, output, and decision state.
