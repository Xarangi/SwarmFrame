# Sources without persistent identities

Some sources record activity without stable agent identities: scan reports of web requests, anonymous traffic,
single-shot episodes. Individual agents are largely distinct, so "which agent did this" has no answer.

## What changes

- **The unit is the target, not the agent.** Cohorts group targets (the resources acted on) by the mix of methods
  used against them and by rate. Outliers are targets whose pattern changed or differs from similar targets.
- **Coordination is inferred from targets, methods and timing.** Bursts of reports on one target within hours, the same
  method class appearing on several targets at once, a method new to a target. Without identities, "one actor" and
  "many actors doing the same thing" are usually indistinguishable; say so.
- **Evidence grades come from the source.** Respect the source's own confidence grades (for example strong versus
  suggestive attribution). A suggestive report is not upgraded by volume alone; many suggestive reports on one target
  in one hour are a stronger pattern than the same reports spread over a month, but each is still suggestive.
- **Identity-centric questions are out of scope.** Do not ask which agent, how many agents, or whether an agent
  changed its behaviour. Ask which targets, which methods, when, and with what confidence.

## Episodes

An episode is a burst: many reports on one target, or one method across targets, inside a short span after a quiet
period. Describe an episode by target, method mix, start and end, peak rate, report count by confidence grade, and
what preceded and followed it on the same target.
