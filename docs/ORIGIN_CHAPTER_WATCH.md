# Watch an explicitly enrolled Origin book

The local runtime can now wait for later chapter requests without an agent
restarting it after every chapter. This is **one enrolled book**, not automatic
enrollment of every tester, a provider-account allocator, or a deployed daemon.
It preserves the private input and journal contract in
[ORIGIN_CHAPTER_LOCAL_CYCLE.md](ORIGIN_CHAPTER_LOCAL_CYCLE.md).

```sh
python3 -m scripts.origin_chapter_runtime \
  --configuration-path /private/approved-book-runtime.json \
  --hub-origin http://127.0.0.1:15099 --hub-host chummer.run \
  --token-file /private/worker.token --output-root /private/provider-journals \
  --watch-seconds 3600 --poll-interval 30
```

The selected profile, account, book, initial work, source scope and chapter/credit
limits must already be explicitly approved. Use the same private journal root on
restart; never create a new root to get past retained custody. BrowserAct and the
approved profile must be available in the execution environment. Do not expose
browser control, tokens, journals or the Hub worker listener publicly.

The watcher:

- checks pending work for only this book; idle polls open no browser;
- uses a new owned window only for an admitted chapter and closes it after a
  confirmed result; the existing runtime verifies the visible account;
- waits for the user's exact predecessor acceptance before starting a later
  requested chapter, never accepting prose or requesting a chapter itself;
- keeps the original one-existing-book-credit ceiling, reusing the paid book;
- rereads the owner-only configuration before **every** observation/dispatch
  tick, including while a provider operation is in flight;
- stops on revocation, changed account/profile/scope/budget, removed input,
  transport errors, ambiguous results or retained browser custody;
- cannot extend its initial expiry, runs at most 24 hours, and uses a monotonic
  lifetime so moving the wall clock backwards cannot prolong execution.

Only a typed transient failure of an idle book's pending-queue GET is observed
again at the existing bounded poll interval (`hub_queue_unavailable`). At this
boundary there is no unfinished local chapter, new packet, execution admission
or provider/browser action. Custody and the original budget/expiry remain intact.
This applies to the single-book watch and the finite pool. It does not clear a
previously retained execution fence or recover an old stopped controller.

Other errors are not retried. An incomplete provider operation keeps its original
session and journals for reconciliation. A changed expiry requires a new
explicit invocation; it cannot silently extend a running watch. Do not configure
an unconditional restart loop around an error. Inspect retained state first.
Signals/process death retain the existing durable fences; they are not a new
generation or credit authorization.

On normal lifetime expiry the result is `watch_finished`. A chapter/final-slot
limit also terminates normally. A returned unresolved state exits with code 2;
exceptions exit nonzero. Neither outcome implies publication or user acceptance.

## Verification and activation boundary

Focused simulated-provider tests cover idle-to-next-chapter operation, separate
reader acceptance, one-credit reuse, process restart without duplicate work,
mid-generation revocation, changed enrollment, transport failure, retained
sessions, finite expiry and clock rollback. They are not live provider or
physical Play proof.

This source addition does not enable a service, enroll more books, renew expired
approvals, spend a credit or restart the general EA stack. A local deployment must
explicitly supply the approved enrollment and the existing private custody.
Continuous operation for arbitrary tester books still needs a bounded enrollment
and account-capacity policy; that is not inferred from consent to character facts.

The separately approved [finite book pool](ORIGIN_BOOK_POOL.md) adds cumulative
new-book admission for one fixed account/profile. It does not enlarge an existing
single-book grant or change the reader-acceptance and reconciliation boundaries.

## Isolated BrowserAct lifecycle compatibility

The local Origin image pins BrowserAct 1.1.0. Its periodic orphan-browser scan
can otherwise kill a newly starting Chrome before its public session is recorded.
The container-only Python bootstrap serializes `browser.open` with that scan in
each command daemon, including at cold start. It does not remove cleanup, change
vendor timeouts, retry an open, delete profile locks or reopen paid work. Health
and other commands remain independent of this lock. A timed-out maintenance
observer does not release a scan's lock before the scan thread actually finishes.

The guard loads in the CLI and auto-launched daemon through the image's scoped
`PYTHONPATH`, not in the host BrowserAct installation. Version/installation failure
stops Python with a redacted error (exit 78); it must never silently run without
the guard. Changing the pinned vendor requires a separate compatibility check.
Focused ordering tests do not by themselves prove a live provider generation.
