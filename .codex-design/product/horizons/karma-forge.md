# KARMA FORGE

## The problem

Groups want house rules and alternate rule environments without forking themselves into incompatible chaos.

## What it would do

Chummer would let groups publish, review, and reuse house-rule sets with visible impact and compatibility checks, without turning them into private forks.

## Likely owners

* `chummer6-core`
* `chummer6-hub`
* `chummer6-hub-registry`
* `chummer6-ui`

## Discovery-first rule

The first implementation step is not engine work.
The first implementation step is a governed discovery pipeline:

1. public invitation
2. structured pre-screen
3. adaptive interview
4. normalized `HouseRuleDemandPacket`
5. EA clustering
6. Product Governor decision
7. prototype only after trust and scope are known

## First flagship discovery lane

KARMA FORGE is the first flagship use of the LTD discovery stack.

Primary workflow:

* `FacePop` public prompt
* `Deftform` pre-screen
* `Icanpreneur` adaptive interview
* `Lunacal` high-signal follow-up
* `MetaSurvey` quant validation
* `NextStep` governed sprint/process execution
* Product Governor classification into candidate or reject/defer routes

## Canonical outputs

KARMA FORGE discovery does not route raw interview notes directly into implementation.
It must normalize into Chummer-owned outputs such as:

* `HouseRuleDemandPacket`
* `KarmaForgeCandidate`
* `RuleEnvironmentImpactHypothesis`

Detailed workflow canon:

* [KARMA_FORGE_DISCOVERY_AND_HOUSE_RULE_INTAKE.md](/docker/chummercomplete/chummer6-design/products/chummer/KARMA_FORGE_DISCOVERY_AND_HOUSE_RULE_INTAKE.md)
* [HOUSE_RULE_DISCOVERY_REGISTRY.yaml](/docker/chummercomplete/chummer6-design/products/chummer/HOUSE_RULE_DISCOVERY_REGISTRY.yaml)
* [ICANPRENEUR_DISCOVERY_AND_VALIDATION_LANE.md](/docker/chummercomplete/chummer6-design/products/chummer/ICANPRENEUR_DISCOVERY_AND_VALIDATION_LANE.md)

## Tool posture

External tools may recruit, pre-screen, interview, schedule, quantify, or explain.
They may not become rule truth, package truth, compatibility truth, or implementation priority truth.

Rule authority stays inside:

* engine packages
* registry compatibility metadata
* activation receipts
* explicit approval paths
* Product Governor decisions

## What has to be true first

* ruleset ABI discipline
* clear package ownership
* registry compatibility metadata
* approval and publication flows

## Why it is not ready yet

Rule changes can fracture tables quickly if compatibility and rollback are not already dependable.
