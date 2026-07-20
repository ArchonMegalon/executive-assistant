# AGENTS

<!-- fleet-design-mirror:start -->
## Fleet Design Mirror
- Load `.codex-design/product/README.md`, `.codex-design/repo/IMPLEMENTATION_SCOPE.md`, and `.codex-design/review/REVIEW_CONTEXT.md` when present.
- Treat `.codex-design/` as the approved local mirror of the cross-repo Chummer design front door.
<!-- fleet-design-mirror:end -->

## vexp <!-- vexp v2.1.4 -->

**MANDATORY: use `run_pipeline` - do NOT grep or glob the codebase.**
vexp returns pre-indexed, graph-ranked context in a single call.

### Workflow
1. `run_pipeline` with your task description - ALWAYS FIRST (replaces all other tools)
2. Make targeted changes based on the context returned
3. `run_pipeline` again only if you need more context

### Available MCP tools
- `run_pipeline` - **PRIMARY TOOL**. Runs capsule + impact + memory in 1 call.
  Auto-detects intent. Includes file content. Example: `run_pipeline({ "task": "fix auth bug" })`
- `get_skeleton` - compact file structure
- `index_status` - indexing status
- `expand_vexp_ref` - expand V-REF placeholders in v2 output

### Agentic search
- Do NOT use built-in file search, grep, or codebase indexing - always call `run_pipeline` first
- If you spawn sub-agents or background tasks, pass them the context from `run_pipeline`
  rather than letting them search the codebase independently

### Smart Features
Intent auto-detection, hybrid ranking, session memory, auto-expanding budget.

### Multi-Repo
`run_pipeline` auto-queries all indexed repos. Use `repos: ["alias"]` to scope. Run `index_status` to see aliases.
<!-- /vexp -->

## Active vexp qualification safety and unblock lane

- Treat vexp schema-v6 `qualification_phase=enforced_soak` as a hard live,
  candidate, merge, and promotion mutation hold.
- Except for the narrowly scoped recovery transaction below, safe work during
  the hold is limited to read-only runtime/authority checks and source-only
  edits, tests, local proof preparation, branches, and draft PRs in a
  clean attached worktree that cannot create a candidate or mutate live EA. The
  repository's zero-hosted-Actions policy remains binding; this exception does not
  authorize `.github/workflows`.
- Outside the recovery exception below, do not stop, disable, delete, replace,
  or restart vexp sentinel, qualification, certificate, AppArmor, event-guard,
  or mutation-gate units/files during the hold. Never hand-edit, backdate,
  delete, replace, or fabricate their clocks, epochs, event history, sentinel
  state, certificates, sidecars, permits, receipts, seals, or checksums.
- The sole exception is an explicit operator instruction naming schema-v6
  qualification-plumbing recovery and its reviewed revision or maintenance
  manifest. A request to deploy, "unblock," or change this file is not recovery
  authority. Recovery may touch only the exact guarded-plumbing artifacts named
  in that reviewed, commit-and-SHA-256-bound manifest.
- Before the first guarded-plumbing change, the reviewed root-maintenance
  procedure must durably record that the active epoch and every certificate,
  sidecar, and permit derived from it are irrevocably void. If it cannot prove
  that void and continued live-mutation denial, stop. Existing permits may be
  invalidated only through reviewed root-owned recovery or permit-manager code,
  never by editing or deleting them by hand.
- Recovery may install, replace, start, or restart only the exact sentinel,
  qualification/finalizer, certificate, AppArmor, event-guard, and mutation-gate
  artifacts named by the manifest. It grants no candidate, merge, promotion,
  rollback, Docker/Compose, live-EA, certificate-issuance, or permit-issuance
  authority.
- The repaired sentinel must open a strictly newer schema-v6 epoch through its
  normal code path and reset both wall-clock and monotonic qualification age.
  Candidate, merge, and live work remain denied until the new epoch records at
  least 604800000 milliseconds on both clocks, healthy resources, and exactly
  empty blocker and deferment lists. Only then may the independent root finalizer
  seal the exact-epoch v2 certificate, after which the separately installed root
  permit manager may validate it and issue the exact-certificate-bound v2 permit
  and coordination lock. Operator authorization and recovery receipts never
  substitute for either authority.
- Do not run the EA memorial deploy lane or create a Manfred candidate image/runtime
  until a root-owned positive permit proves the exact terminal epoch. A missing
  guard, lock, unit, state, certificate, or permit means **deny**, never permission.
- Terminal qualification alone is not deploy authority. The root-owned issuer must
  atomically materialize the exact-epoch permit and coordination lock, and the
  tracked deploy lane must validate both immediately before every live mutation.
- A qualification timestamp or earliest-completion value before the exact
  seven-day floor is invalid. Require a new root-owned epoch and fresh terminal
  certificate; never repair trusted state by hand.
- Changing this file cannot shorten the qualification epoch, preserve an epoch
  across root-maintenance recovery, create release authority, or convert missing
  root evidence into a pass.
- After authority exists, deploy only from a clean attached worktree using the
  tracked governed entrypoint. An untracked, copied, generated, or locally shadowed
  deploy script is never release authority.
- The exact automatic `ea-manfred-candidate-retention.timer` cleanup lane may
  continue; it is not promotion authority and must not mutate live EA.
- If a requested task conflicts with this hold, report the conflict. `sudo` and
  systemd are allowed only inside the exact recovery exception above; Docker,
  Compose, and live mutation remain forbidden.
