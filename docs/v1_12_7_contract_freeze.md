# EA OS v1.12.7 Contract Freeze

Date: 2026-03-04  
Status: Active (implementation started)

## Purpose
Stabilize the 12.x runtime core before expanding features.  
This phase freezes cross-module control-plane contracts so feature modules stop
owning provider-specific and repair-specific internals.

## Frozen Contracts

### 1) Cloud LLM Gateway Contract
- Module: `app/contracts/llm_gateway.py`
- Function: `ask_text(prompt: str, *, system_prompt: str = ...) -> str`
- Rule: feature modules call this adapter, never provider HTTP endpoints directly.
- Current adopters: `app/briefings.py`

### 2) Mum Brain Repair Contract
- Module: `app/contracts/repair.py`
- Function: `open_repair_incident(...) -> str`
- Rule: feature modules open recovery incidents via this adapter, not direct
  calls to `trigger_mum_brain`.
- Current adopters: `app/briefings.py`, `app/poll_listener.py`

### 3) Telegram Safety Contract
- Module: `app/contracts/telegram.py`
- Functions:
  - `sanitize_user_copy(text, *, placeholder=False) -> str`
  - `sanitize_incident_copy(text, *, correlation_id, mode) -> str`
- Rule: user-visible fallback/error text must pass through contract sanitizers.
- Current adopters: `app/briefings.py` (incident-safe fallback copy)

## Runtime Invariants
1. No direct provider LLM HTTP calls from feature modules.
2. No direct `trigger_mum_brain` imports in feature modules.
3. User-facing fallback text remains sanitized at Telegram boundary.
4. API role and poller role startup behavior remains role-gated.

## Migration Checklist (next patches)
1. Route remaining LLM call sites through `contracts.llm_gateway`.
2. Route remaining Telegram send/edit/error paths through `contracts.telegram`.
3. Extract poller interaction orchestration from `poll_listener.py` into a
   dedicated interaction service.
4. Keep scheduler limited to scheduling/prewarm responsibilities.

## Definition of Done
1. Feature modules use only contracts for LLM, repair, and fallback copy.
2. Contract-level smoke tests enforce these invariants.
3. README references this contract freeze as the stabilization baseline.

