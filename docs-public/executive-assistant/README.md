# Executive Assistant Public Docs

This package is the source-controlled public documentation seed for the Executive Assistant Documentation.AI site.

Target site:

```text
docs.<executive-assistant-domain>
```

Use this package as a dedicated public documentation repository. If Documentation.AI needs API context, connect only a sanitized public schema repository. Do not connect the private EA runtime repository, support exports, provider logs, credentials, incident notes, or internal runbooks as context.

## Documentation.AI setup

1. Create an organization named `Executive Assistant`.
2. Create one documentation project for `docs.<executive-assistant-domain>`.
3. Connect a public docs repository containing this folder.
4. Optionally connect one sanitized public schema repository.
5. Keep provider writeback disabled unless a human review gate has accepted the exact diff.

Documentation.AI context repositories are read-only context for its AI agent and are separate from Git sync. Keep the project under the two-context-repository limit by using only the public docs repo and optional public schema repo.

## Public scope

Allowed:

- Product overview and onboarding guides
- Gmail, Calendar, Telegram, and WhatsApp setup explanations
- Approval and permission concepts
- Reviewed troubleshooting articles
- Sanitized public OpenAPI reference
- `llms.txt` for public AI crawlers and assistants
- Changelog entries approved for public release

Excluded:

- Security runbooks and incident details
- Credentials, provider keys, tokens, and account recovery material
- Customer records, exact messages, private documents, or decision history
- Operator-only prompts, model routing, fleet routes, and internal CodexEA endpoints
- Full private OpenAPI exports

## Commands

Materialize the sanitized public OpenAPI package from the current live snapshot:

```bash
python3 scripts/materialize_documentation_ai_public_docs.py --require-source
```

Verify the public package before publishing or syncing:

```bash
python3 scripts/verify_documentation_ai_public_docs.py
```

Write a deployment readiness receipt without failing on missing external configuration:

```bash
make materialize-documentation-ai-deployment-readiness
```

Require a real Documentation.AI deployment proof:

```bash
# Replace every <...> value with the live Documentation.AI project receipt.
DOCUMENTATION_AI_EA_ORG="Executive Assistant" \
DOCUMENTATION_AI_EA_SITE_URL="https://<real-docs-domain>" \
DOCUMENTATION_AI_EA_CONTEXT_REPOS="<public-docs-repo>,<optional-public-schema-repo>" \
DOCUMENTATION_AI_EA_CUSTOM_DOMAIN_STATUS="verified" \
DOCUMENTATION_AI_EA_SSL_STATUS="active" \
DOCUMENTATION_AI_EA_PUBLISH_STATUS="published" \
DOCUMENTATION_AI_EA_PUBLISHED_GIT_HEAD="$(git rev-parse HEAD)" \
make verify-documentation-ai-deployment-readiness
```

Run the focused test suite:

```bash
PYTHONPATH=ea python3 -m pytest -q tests/test_documentation_ai_public_docs.py
```
