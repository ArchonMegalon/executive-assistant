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
* ProductLift ideas, votes, comments, and closeout candidates
* Katteb public guide/content audit findings
* ClickRank crawl, metadata, schema, broken-link, internal-link, and AI-search visibility findings
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
* whether the item is support, public signal, content optimization, discovery, or canon work

Detailed packet routing lives in `FEEDBACK_AND_SIGNAL_OODA_LOOP.md`.

## Decide

The legal outcomes are:

* code fix
* docs/help fix
* queue or package change
* policy change
* canon change
* release action
* public roadmap/changelog projection update
* public guide/source-registry update
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

ProductLift-linked closure requires Chummer-owned release, guide, Hub route, artifact, or explicit no-change evidence before a public shipped claim or voter notification.

Katteb-linked closure requires an upstream source change or explicit rejection before generated guide or article copy changes.

ClickRank-linked closure requires a Hub/design source, metadata config, registry, or article-source change plus regeneration or explicit no-change rationale before public output changes.

Detailed closure semantics live in `FEEDBACK_AND_CRASH_STATUS_MODEL.md`.

## Contract family

This loop compiles into `Chummer.Control.Contracts`, not into ad hoc markdown-only folklore.
