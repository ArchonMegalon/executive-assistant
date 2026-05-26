# LOCAL CO-PROCESSOR

## The problem

Some explain, search, and media-assist workloads would be cheaper, faster, or more private with optional local acceleration, but the product cannot require every user to run local compute.

## What it would do

Chummer would allow optional local acceleration or lightweight host strategies where they improve responsiveness, privacy, or cost.
The same workflows must still function in hosted-only mode, and no canonical truth may depend on local runtime availability.

## Likely owners

* `chummer6-core`
* `chummer6-ui`
* `chummer6-mobile`

## Key tool posture

* no mandatory external tool
* optional bounded use of `1min.AI`, `AI Magicx`, or other helpers where local orchestration benefits from acceleration evidence

## What has to be true first

* portable deterministic engine host strategy
* hosted-first parity
* explicit non-mandatory local runtime policy
* disableable local acceleration paths

## Why it is not ready yet

Local acceleration is only a win if it remains optional.
Until Chummer can prove that local compute improves the product without becoming a hidden requirement, this stays a horizon rather than a foundation promise.
