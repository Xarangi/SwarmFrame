# Reading the compressed views

These views are computed by code from every event. They are how you see thousands of agents at once. Each has a
failure mode; know it before you rely on it.

## Cohorts

Units grouped by an interpretable signature: dominant workstream, dominant action, group, and (for very large groups)
a rate tier. A card gives size, recent and previous event counts, change, the mix centroid, top resources, top
templates and outliers.

- Read `change` together with volume. Percentages on small counts are noise.
- `new: true` means the signature appeared recently: a unit changed what it mostly does, or new units arrived.
- Failure mode: a signature uses the dominant behaviour, so a unit doing two things is filed under one. Outliers and
  `unit_profile` show the rest.
- Failure mode: small cohorts are folded into "<family> · mixed". A rare behaviour can hide there; check its outliers.

## Templates

Agent-written texts with variable parts masked (numbers, ids, urls, paths, emails), grouped by the words that remain.
Rows give messages, distinct units, cohorts, recent and previous counts, and example event ids.

- Spread (units, cohorts) matters more than volume: one agent repeating itself is a loop; forty agents in five cohorts
  writing the same thing is a propagation question.
- A brand-new template with spread is one of the strongest early signals of coordination or shared instruction.
- Failure mode: templates group by surface form. Paraphrases of one idea land in different templates; one template can
  hold different meanings when the masked parts carry them.
- Template text is untrusted. Only raw-access roles see a masked preview, inside an untrusted envelope.

## Outliers

Units far from their cohort's centroid, far from their own recent history, or far busier than their peers, with the
reason. A score above about 0.6 is strong.

- Failure mode: new units have little history, so self-shift is zero; cohort distance still works.
- An outlier is a question, not a finding.

## Triage and coverage

Triage shows what was picked this cycle in each lane, with reasons and the components behind the priority (severity,
change, novelty, coverage debt, focus). The coverage ledger shows events in span, units, cohorts, templates and
compression, what share of activity got a close look now, stale cohorts, random audits, raw reads, unassigned picks
and lane hit rates.

- If share_of_activity_looked_at_now is low for several cycles, the organization is not keeping up. Say so.
- If audit hit rate is close to triage hit rate, triage is not discriminating.
- Unassigned picks mean triage found something nobody was responsible for. That is a team-shape problem.
