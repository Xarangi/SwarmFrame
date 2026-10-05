/* One glossary for every label a person reads. Internal names stay in the code; the screen says what they mean, in
   the source's own nouns (agent / report, resource / target / file). Every entry has hover help. */

export interface Terms { agent: string; resource: string }

export const DEFAULT_TERMS: Terms = { agent: 'agent', resource: 'resource' }

type Entry = { label: (t: Terms) => string; help: (t: Terms) => string }

const E: Record<string, Entry> = {
  cohort: { label: (t) => `group of similar ${t.agent}s`, help: (t) => `${cap(t.agent)}s that behave alike: the same kind of work, in the same places, at a similar pace.` },
  cohorts: { label: (t) => `groups of similar ${t.agent}s`, help: (t) => `${cap(t.agent)}s that behave alike: the same kind of work, in the same places, at a similar pace.` },
  unit: { label: (t) => t.agent, help: () => '' },
  triage: { label: () => 'reading plan', help: () => 'What the analysts will read closely this cycle, and why each item was picked.' },
  lane_triage: { label: () => 'priority', help: () => 'Picked because it scored highest: severity, change, novelty and how long since anyone looked.' },
  lane_coverage: { label: () => 'unread longest', help: () => 'Picked because nobody has read it for the longest time, so nothing goes unread forever.' },
  lane_audit: { label: () => 'spot-check', help: () => 'Picked at random (with a seed nobody can predict), to catch what the scoring misses.' },
  coverage: { label: () => 'read closely', help: () => 'Share of recent activity that an analyst read closely, rather than only counted.' },
  coverage_ledger: { label: () => 'what we have read', help: () => 'Which groups got a close look this cycle, and which did not.' },
  blind_spots: { label: () => 'not yet read', help: () => 'Groups or picks that nobody has looked at yet.' },
  template: { label: () => 'message type', help: () => 'Messages with the same shape once names and numbers are masked out. The wording itself stays hidden.' },
  outlier: { label: (t) => `unlike its group`, help: (t) => `How far this ${t.agent}'s behaviour is from its group's, from 0 (typical) to 1 (very different).` },
  organization: { label: () => 'the reading team', help: () => 'The AI readers SwarmFrame runs for this stream. Their roles, how the population is split between them and when a person is interrupted are the team shape, shown on the Organization page.' },
  health: { label: () => 'monitor health', help: () => 'Whether the monitoring itself is working: how much it reads, where it disagrees, what it cannot see.' },
  disagreement: { label: () => 'analysts disagree', help: () => 'How often two independent evaluations of the same evidence reached different conclusions.' },
  brief: { label: () => 'live brief', help: () => 'What SwarmFrame noticed, newest first. Updated as it learns; earlier entries are revised, not deleted.' },
  investigation: { label: () => 'investigation', help: () => 'A focused look at one finding by a small team of analysts, with a budget.' },
  acknowledge: { label: () => 'acknowledge', help: () => 'Take receipt of an escalation. The team stops counting it as unanswered; it stays open until you dismiss it.' },
  case: { label: () => 'tracked finding', help: () => 'One finding the team is tracking: who saw it, how its level changed, and whether a person has acknowledged it.' },
  directive: { label: () => 'suggestion', help: () => 'Something SwarmFrame proposes to change about where it looks. You can apply or reject it.' },
}

export function term(key: string, t: Terms = DEFAULT_TERMS): string {
  return E[key]?.label(t) ?? key
}
export function help(key: string, t: Terms = DEFAULT_TERMS): string {
  return E[key]?.help(t) ?? ''
}
export const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s)

/* ------------------------------------------------------------------ severity */
export const SEVERITY: Record<string, { label: string; help: string; color: string }> = {
  ACT: { label: 'Act', help: 'Needs a decision from you now.', color: 'var(--sev-act)' },
  LOOK: { label: 'Look', help: 'Worth a look: open the evidence or the investigation.', color: 'var(--sev-look)' },
  WATCH: { label: 'Watch', help: 'Being watched; no action needed unless it grows.', color: 'var(--sev-watch)' },
}

export const EVIDENCE: Record<string, { label: string; help: string; color: string }> = {
  observed: { label: 'observed', help: 'Seen directly in the event record.', color: 'var(--st-observed)' },
  derived: { label: 'derived', help: 'Computed from observed events (counts, rates, overlaps).', color: 'var(--st-derived)' },
  claimed: { label: 'claimed', help: 'An agent said so; not yet checked against what it did.', color: 'var(--st-self)' },
  inferred: { label: 'inferred', help: 'An interpretation by an analyst, not an observation.', color: 'var(--st-inferred)' },
}

/* The incident's risk axes, each with the sentence that explains it. */
export const AXES: { key: string; label: string; help: (t: Terms) => string }[] = [
  { key: 'coordination', label: 'Coordination', help: (t) => `How strongly the evidence suggests ${t.agent}s acting together.` },
  { key: 'impact', label: 'Impact', help: () => 'What it could affect if it is what it looks like.' },
  { key: 'scope', label: 'Scope', help: (t) => `How many ${t.agent}s or ${t.resource}s are involved.` },
  { key: 'external', label: 'Outside reach', help: () => 'Whether it touches things outside the swarm (the web, people, other systems).' },
  { key: 'novelty', label: 'Novelty', help: () => 'How unlike anything seen before in this stream it is.' },
  { key: 'evidence', label: 'Evidence', help: () => 'How much of it rests on direct observation rather than inference.' },
]

/* Briefing kinds in plain words. */
export const CHANGE_KIND: Record<string, string> = {
  NEW: 'New', UPDATE: 'Updated', REVISED: 'Revised', STATUS: 'Status', CONTROL: 'Control', HUMAN: 'You',
}

/* Glance numbers a person can pick for the Brief. */
export const GLANCE_HELP: Record<string, string> = {
  active: 'How many are active in the most recent windows.',
  attention: 'Findings rated Act or Look, after grouping duplicates.',
  watching: 'Findings being watched that need no action yet.',
  investigating: 'Investigations running right now.',
  coverage: 'Share of recent activity an analyst read closely rather than only counted: under 15% is thin, under 40% fair, above that good.',
  events: 'Events received since the start.',
  approvals: 'Tool calls waiting for your approval.',
  total: 'Every record in the catalog up to the replay clock.',
  recent: 'Records in the last 30 days, compared with the 30 days before.',
  targets: 'Distinct targets named in the catalog so far.',
  significant: "The source's own confidence: the share of records it grades significant rather than suggestive.",
}
