# Support and signal OODA loop

## Purpose

This file defines how Chummer closes the loop from user pain back into governed product change.

It sits above the detailed support and packet docs and names the full path:

1. observe
2. orient
3. decide
4. act
5. close

## Observe

Raw inputs include:

* crash reports
* structured bug reports
* lightweight feedback
* surveys
* public issues
* release regressions
* public-promise drift findings

Detailed intake posture lives in `FEEDBACK_AND_CRASH_REPORTING_SYSTEM.md`.

## Orient

Signals become one bounded packet with:

* who is hurt
* how often
* what release or channel is affected
* whether the failure is code, docs, policy, queue, or canon
* whether trust, release safety, or roadmap honesty is at risk

Detailed packet routing lives in `FEEDBACK_AND_SIGNAL_OODA_LOOP.md`.

## Decide

The legal outcomes are:

* code fix
* docs/help fix
* queue or package change
* policy change
* canon change
* release action
* defer or reject with explicit rationale

## Act

The packet must land in one owning lane.

It is not enough to:

* cluster the report
* draft a note
* merge a PR

The control plane is only healthy when the accepted packet became a real owned action.

## Close

The loop is not closed until reporter-facing or public-facing truth changed where appropriate.

Detailed closure semantics live in `FEEDBACK_AND_CRASH_STATUS_MODEL.md`.

## Contract family

This loop compiles into `Chummer.Control.Contracts`, not into ad hoc markdown-only folklore.
