export type ClaimStatus = 'OBSERVED' | 'DERIVED' | 'SELF_REPORTED' | 'INFERRED' | 'CONTRADICTED' | 'UNKNOWN'
export type Level = 'NONE' | 'WATCH' | 'INVESTIGATE' | 'ALERT' | 'PAGE' | 'INFO'

export interface EvidenceRef { kind: string; id: string; note?: string | null }
export interface Claim {
  id: string; statement: string; status: ClaimStatus; support: EvidenceRef[]; counter: EvidenceRef[]
  confidence: number; author: string; ts: string | null; scope: string | null
}
export interface BriefingEntry {
  id: string; ts: string; text: string; kind: 'NEW' | 'UPDATE' | 'REVISED' | 'STATUS' | 'CONTROL' | 'HUMAN'
  claims: string[]; confidence: number; level: Level
}
export interface RiskVector {
  impact: number; scope: number; coordination_evidence: number; external_capability: number; novelty: number
  evidence_strength: number; monitor_integrity: number; uncertainty: number
}
export interface MonitorReport {
  id: string; monitor: string; window_end: string; scope: string; headline: string; observations: string[]
  claims: string[]; questions: string[]; risk: RiskVector; escalation: Level; summary: string
  strategies: Record<string, string>; cost_usd: number; tokens: number; disagreement: number | null
}
export interface Answer { text: string; status: string; claims: string[]; confidence: number; unresolved: string[] }
export interface Question {
  id: string; text: string; priority: string; requested_by: string; scope: string | null; kind: string
  status: string; created: string | null; answer: Answer | null; blocked_reason: string | null
}
export interface InvestigationNode {
  id: string; parent: string | null; role: string; title: string; status: string; claims: string[]
  summary: string | null; spent_usd: number; tokens: number; requested_by: string
}
export interface Investigation {
  id: string; question_id: string; title: string; scope: string | null; nodes: InvestigationNode[]; status: string
  budget_usd: number; spent_usd: number; opened: string | null; concluded: string | null; conclusion: string | null
  pinned: boolean
}
export interface Directive {
  id: string; ts: string; kind: string; scope: string | null; payload: Record<string, unknown>; reason: string
  set_by: string; status: string; executive_version: number | null
}
export interface Focus { scope: string; weight: number; reason: string; set_by: string; expires: string | null }
export interface LedgerEntry { id: string; kind: string; text: string; pinned_by: string; sticky: boolean; evidence: EvidenceRef[] }
export interface Incident { id: string; title: string; scope: string; level: Level; opened: string; status: string; investigation: string | null; risk: RiskVector; reports: string[] }
export interface Hypothesis { id: string; text: string; status: string; confidence: number; support: string[]; against: string[] }
export interface Workstream { id: string; label: string; actors: number; events: number; trend: string; note: string }

export interface TeamSummary {
  topology: string; title: string; description: string; by: 'override' | 'pack' | 'selector' | 'default' | 'human'; reasons: string[]
  would_pick: string | null; would_pick_reasons: string[]; shape: Record<string, any>; axes: { field: string; distinct: number; share: number | null }[]
  partition: Record<string, any>; levels: any[]; standing: any[]; questions: Record<string, string>; cadence: Record<string, any>
  human: Record<string, any>; authority: Record<string, any>
  roles: Record<string, { title: string; model: string; effort: string; scope: string; description: string }>
  alternatives: { id: string; title: string }[]
}
export interface Proposal {
  id: string; ts: string; by: string; kind: 'role' | 'change' | 'topology'; payload: Record<string, any>; reasons: string[]
  status: 'pending' | 'approved' | 'applied' | 'declined' | 'failed' | 'reverted'; note: string; needs: string[]; title: string; describe: string
}
export interface ApprovalsSummary { pending: Proposal[]; recent: Proposal[]; count: number; envelope: Record<string, any>; approvals_needed: string[] }
export interface Delegation { ts: string; stream_ts: string; cycle: number; kind: string; by: string; role: string; node: string | null; target: string; why: string; brief: string; outcome: string; cost_usd: number; note_kind?: string }
export interface Snapshot {
  empty?: boolean
  team?: TeamSummary
  approvals?: ApprovalsSummary
  delegations?: { path: string; total: number; by_kind: Record<string, number>; recent: Delegation[] }
  scope_labels: Record<string, string>
  source: { id: string; title: string; noun: string; synthetic: boolean; live: boolean; goal: string }
  clock: { live: boolean; now: string; start: string; end: string | null; speed: number; paused: boolean; window_s: number; progress: number | null; index: number; done: boolean }
  org: { id: string; name: string; autonomy: string; llm_mode: string; llm_label?: { short: string; long: string }; executive_strategy: string; monitors: string[] }
  executive: {
    version: number; ts: string | null; population_state: string; workstreams: Workstream[]; important_changes: string[]
    hypotheses: Hypothesis[]; open_questions: string[]; active_incidents: Incident[]; blind_spots: string[]
    strategy: string; meta: Record<string, unknown>; last_run_index: number
  }
  ledger: { version: number; entries: LedgerEntry[] }
  briefing: BriefingEntry[]
  reports: MonitorReport[]
  claims: Record<string, Claim>
  questions: Question[]
  investigations: Investigation[]
  directives: Directive[]
  attention_policy: Focus[]
  attention: { by_scope: AttentionRow[]; by_role: Record<string, number>; records: number }
  health: {
    coverage: number; inspected_events: number; events_seen: number; disagreement: number | null; blind_spots: number
    errors: string[]; monitors: Record<string, { reports: number; level: string; spent_usd: number; tokens: number; slots: Record<string, string> }>
    llm_mode: string; spent_usd: number
  }
  population: { active: number; hours: number; families: { family: string; now: number; prev: number; actors: number }[]; total_events_seen: number }
  control: ControlSummary | null
  scale?: ScaleSnapshot
  dashboard_version?: number
  lens?: string
  brief?: Brief
  world?: { version: number; window: number; shape: string; flags: Record<string, number> }
  autoplay?: number | string | null
  speeds?: Speed[]; replay_hours?: number | null
  live_replay?: { at: string; end: string | null; label: string; window_s: number; warmup_min: number; on: boolean } | null
  session_id?: string
  stream?: { received: number; feed: { agents: number; hours: number; speed: number; events: number; sent: number } | null } | null
}
export interface AttentionRow { scope: string; label: string; monitors: string[]; investigators: number; calls: number; tokens: number; cost_usd: number; focus: number }
export interface ControlSummary {
  agents: number; statuses: Record<string, number>; runner_connected: boolean; simulated: boolean; policy_enabled: boolean
  pending: { id: string; agent: string; label: string; tool: string; input: string; ts: string; timeout_s: number; default: string }[]
  actions: { id: string; ts: string; kind: string; target: string; result: string; actor: string }[]
  spent_usd: number
}
export interface Capability { present: boolean; quality: string; note: string }
export interface Speed { v: number | 'max'; label: string; note?: string }
export interface SourceInfo {
  play_default?: 'live' | 'replay'; id: string; title: string; description: string; live: boolean; noun: string; has_data: boolean; fetch_sets: string[]; capabilities: Record<string, Capability>
  speeds?: Speed[]; autoplay?: number | string | null; replay_hours?: number | null; replay_hours_synthetic?: number | null
  replay_hours_full?: number | null; slice?: { start?: string; end?: string; label?: string } | null
  live_stretch?: LiveStretch | null }
export interface LiveStretch { start: string; end: string; window_seconds?: number; warmup_minutes?: number; label?: string; rate?: string }

/* ---------------------------------------------------------------- scale layer */
export interface CohortCard {
  id: string; label: string; units: number; events_now: number; events_prev: number; change: string; new: boolean
  size_change: number | null; mix: Record<string, number>
  top_resources: { id: string; label: string; events: number }[]
  top_templates: { id: string; events: number; units: number }[]
  outliers: { unit: string; label: string; score: number; why: string }[]
}
export interface TriageItem {
  scope: string; kind: string; label: string; priority: number; lane: 'triage' | 'coverage' | 'audit'
  components: Record<string, number>; reasons: string[]; cohort: string | null; assigned_to: string | null; n_units: number
}
export interface Coverage {
  cycle: number; events_in_span: number; events_total: number; units_active: number; units_seen: number; cohorts: number
  templates: number; messages: number; compression: number; cohorts_looked_at_now: number; cohorts_looked_at_recently: number
  share_of_activity_looked_at_now: number | null; units_looked_at_now: number; random_audits_now: number; raw_reads_now: number
  agent_runs_now: number; stale_cohorts: { id: string; label: string; events_now: number }[]; stale_cohorts_total: number
  unassigned_picks: string[]; uncovered_divisions: string[]; hit_rates: Record<string, number | null>; warnings: string[]
}
export interface ScaleSnapshot {
  population: { unit: string; units_seen: number; units_active: number; cohorts: number; events_total: number; events_now: number
    events_prev: number; texts: number; templates: number; messages: number; compression: number; outliers: number; largest_cohort: number }
  cohorts: CohortCard[]
  templates: { id: string; messages: number; units: number; cohorts: number; now: number; prev: number; new: boolean; examples: string[] }[]
  triage: { cycle: number; reads_per_cycle: number; lanes: Record<string, number>; weights: Record<string, number>; items: TriageItem[]
    next_in_line: TriageItem[]; hit_rates: Record<string, number | null>; outcomes: Record<string, Record<string, number>>; warnings: string[] }
  coverage: Coverage | null
  coverage_history: { cycle: number; share_of_activity_looked_at_now: number | null; cohorts_looked_at_now: number; random_audits_now: number; stale_cohorts_total: number; agent_runs_now: number }[]
  sectors: number; divisions: number
}

/* ---------------------------------------------------------------- dashboard spec */
export interface ViewSpec { primitive: string; query: Record<string, any>; options: Record<string, any> }
export interface PanelSpec { id: string; title: string; blurb: string; span: number; kind: 'builtin' | 'view'; builtin: string | null; view: ViewSpec | null }
export interface PageSpec { id: string; title: string; description: string; icon: string; panels: PanelSpec[]; by: string; nav: 'brief' | 'activity' | 'top'; reason: string }
export interface BriefSpec { glance: string[]; attention_rows: number; min_severity: 'ACT' | 'LOOK' | 'WATCH'; show_changes: boolean; world?: boolean; overview?: boolean; pinned: string[]; snoozed: string[] }
export interface DashboardSpec {
  source: string; version: number; title: string; terminology: Record<string, string>
  pages: PageSpec[]; by: string; rationale: string; updated: string | null; brief: BriefSpec; machinery: boolean
}
export interface DashState {
  spec: DashboardSpec; history: { version: number; by: string; rationale: string }[]
  builtins: Record<string, string>; primitives: Record<string, string>; designing: boolean
  lens: string; lenses: string[]; glance: Record<string, string>; machinery: string[]
}

/* ---------------------------------------------------------------- the Brief */
export type Severity = 'ACT' | 'LOOK' | 'WATCH'
/** A finding in plain words: what happened, why it might matter, the innocent reading, what to check. */
export interface Explain { what: string; why: string; benign: string; check: string }
/** One numbered source behind a finding, narration line or answer (labels only; opens in the evidence drawer). */
export interface Cite { n: number; kind: 'claim' | 'event' | 'entity'; id: string; label: string; status?: string; ts?: string; family?: string | null; type?: string }
export interface FindingRow {
  id: string; kind: string; severity: Severity; headline: string; scope: string; label: string
  fresh: 'new' | 'updated' | 'quiet'; fresh_text: string; opened: string; last: string
  evidence: 'observed' | 'derived' | 'claimed' | 'inferred'; next: string; action: string
  investigation: string | null; investigation_status: string | null; status: string; level: string; reports: number
  pinned: boolean; axes: Record<string, number>
  group?: boolean; count: number; members: string[]; member_rows?: FindingRow[]; detail?: string
  // the findings ledger: who saw it, how it got here, whether a person has taken receipt
  views?: string[]; owner?: string | null; pending_level?: string | null; acknowledged?: string | null; acknowledged_by?: string | null
  overdue?: boolean; needs_ack?: boolean
  cites?: Cite[]
  explain?: Explain
  history?: { ts: string; level: string; by: string; reason: string; held: string | null; evidence: string[] }[]
}
export interface CasesSummary { open: number; alerts: number; unacknowledged: number; overdue: number; held: number; alerts_used: number; alerts_per_cycle: number }
export interface GlanceStat { value: number; label: string; sub: string; unit?: string; series: number[] }
export interface Brief {
  status: string; attention_line: string; updated: string | null; version: number
  counts: Record<Severity, number>; raw_counts: Record<Severity, number>; items: FindingRow[]
  changes: { ts: string; kind: string; label: string; text: string; n: number; id: string }[]
  glance: Record<string, GlanceStat>; terms: { agent: string; resource: string }; identities: boolean
  catalog?: boolean; status_detail?: string; field?: { families: { family: string; actors: number }[]; active: number }
  cases?: CasesSummary
  overview?: import('./components/Overview').OverviewData | null
}
export interface ViewData { columns: string[]; rows: any[][]; meta: Record<string, any> }
