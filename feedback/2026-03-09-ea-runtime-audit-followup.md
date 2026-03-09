# EA runtime audit follow-up

Date: 2026-03-09
Audience: repo owners and Codex worker agents
Status: injected follow-up from fleet audit

## Summary

The EA runtime is materially stronger, but the next queue should prioritize correctness and architecture debt over new feature growth.

Primary required work:
- Fix the `connector.dispatch` contract drift so the declared tool schema matches executor requirements, including `binding_id`.
- Unify connector binding principal-scope enforcement and reject execution when `principal_id` is missing or mismatched.
- Enforce `allowed_channels` at execution time for `connector.dispatch`.
- Add stricter production auth/startup guardrails so prod refuses empty API token configuration.
- Freeze current orchestration behavior with replay or snapshot tests before splitting `orchestrator.py`.
- Split `tool_execution.py` into adapter-focused modules and stop hidden in-memory fallback construction inside the execution service.
- Add a memory reasoning layer for context packs, promotion, conflicts, and commitment risk on top of the existing memory substrate.
- Make worker topology explicit in compose and reduce monolithic smoke or runtime and README sprawl.

## Queue intent

This feedback should drive the next scoped execution slices in this order:
1. connector.dispatch contract correctness and tests
2. connector principal-scope and allowed-channel enforcement
3. production auth guardrails
4. orchestrator replay tests plus first extraction seams
5. tool execution adapter split
6. memory reasoning and context packs
7. worker topology compose and runtime cleanup
8. smoke test and README decomposition
