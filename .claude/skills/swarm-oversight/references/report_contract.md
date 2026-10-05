# Report contract

Every report has a fixed shape. The level above reads many of them side by side, so a report that is longer, vaguer,
or shaped differently costs everyone.

## division_report (analysts, sector leads, auditors)

| Field | Content |
|---|---|
| headline | One sentence the reader can act on. Names the scope, the change and the size. |
| status | quiet, normal, notable, concerning |
| summary | Three to five sentences: the norm, the deviations, what you checked. |
| claims | Graded claims with evidence ids. Usually two to six. |
| flags | Things that deserve a specialist or a question: kind, scope, text, priority. A `concerning` report also opens or updates the case for its scope; call `escalate_finding` yourself when a finding should rise above INVESTIGATE. |
| looked_at | One entry per reading-plan pick: scope, status, finding. Include "nothing notable". |
| blind_spots | What in scope you did not examine, and why. |
| recommend | split, retire, specialist kind, reason. |
| notes_for_next_time | The norm, what you are watching, what you could not check. |

## finding (specialists)

headline, verdict (supported, partially_supported, unsupported, unknown), claims, open_points, notes_for_next_time.

## A good headline and a bad one

Good: "Cohort research · write grew from 120 to 410 events in 6 h; 38 of its 52 agents now write the same new
template, first seen at 14:05 from 2 agents in cohort ops · chat."

Bad: "Significant unusual activity detected in the research area that may warrant further attention."

The good one names the scope, gives counts with bases, says when, and points at the propagation question. The bad one
could be written without looking at anything.

## A good claim and a bad one

Good: `{"statement": "38 of 52 agents in coh_3fa21c wrote template tpl_9e01aa between 14:05 and 15:40",
"status": "DERIVED", "evidence_ids": ["evt_…", "evt_…"], "confidence": 0.9}`

Bad: `{"statement": "The agents are coordinating to evade monitoring", "status": "OBSERVED", "evidence_ids": []}`.
That is an interpretation (INFERRED at most), it has no evidence, and the verifier will downgrade it.
