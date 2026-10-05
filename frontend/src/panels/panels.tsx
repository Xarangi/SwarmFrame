import React, { useEffect, useState } from 'react'
import { api, get } from '../api'
import { useStore } from '../store'
import type { Snapshot } from '../types'
import {
  Bar, ClaimList, ClaimLink, Empty, famColor, fmtNum, fmtTime, Icon, KindChip, LevelChip, pct, ScopeLink, StatusChip,
} from '../components/ui'
import { OrgMini } from '../screens/Organization'
import { CohortsPanel, CoveragePanel, TemplatesPanel, TriagePanel } from './scale'
import { FindingList } from '../components/findings'
import { Term } from '../components/kit'
const WorldMini = React.lazy(() => import('../screens/World').then((m) => ({ default: m.WorldMini })))
import {
  Bipartite, GraphData, Lineage, LineageChain, StackedTimeline, SwimData, Swimlanes, TimelineData, useView,
} from '../primitives/charts'

export type PanelQuestion = 'happening' | 'changed' | 'attention' | 'unknown' | 'control'
export interface PanelDef {
  id: string
  title: string
  blurb: string
  requires: string[]
  span: number
  defaultOn: boolean
  question: PanelQuestion
  render: (s: Snapshot) => React.ReactNode
  kicker?: (s: Snapshot) => React.ReactNode
}

export function useCapabilities(sourceId: string | undefined) {
  const [caps, set] = useState<Record<string, { present: boolean; quality: string; note: string }> | undefined>()
  useEffect(() => {
    if (!sourceId) return
    get('/api/profile').then((p) => set(p.capabilities)).catch(() => {})
  }, [sourceId])
  return caps
}

/* ================================================================== live brief */
function LiveBrief({ s }: { s: Snapshot }) {
  const fresh = useStore((x) => x.freshBriefing)
  const entries = [...s.briefing].reverse().slice(0, 24)
  if (!entries.length) return <Empty title="Nothing to report yet.">SwarmFrame writes here as it learns.</Empty>
  return (
    <div className="brief" style={{ maxHeight: 560, overflow: 'auto', marginRight: -8, paddingRight: 8 }}>
      {entries.map((b) => {
        const claims = b.claims.map((c) => s.claims[c]).filter(Boolean)
        return (
          <div key={b.id} className={`brief-entry k-${b.kind} ${fresh.has(b.id) ? 'fresh' : ''}`}>
            <div className="t">{fmtTime(b.ts)}<div style={{ fontSize: 10, opacity: 0.8 }}>{fmtTime(b.ts, true).slice(0, 5)}</div></div>
            <div>
              <div className="meta"><KindChip kind={b.kind} /><LevelChip level={b.level} /></div>
              <div className="txt">{b.text}</div>
              {claims.length > 0 && (
                <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                  {claims.slice(0, 4).map((c) => (
                    <button key={c.id} className={`chip soft st-${c.status}`} style={{ cursor: 'pointer', textTransform: 'none', letterSpacing: 0 }}
                      onClick={() => useStore.getState().openDrawer({ kind: 'claim', id: c.id })}>
                      <span className="dot" />{c.statement.length > 60 ? c.statement.slice(0, 58) + '…' : c.statement}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ================================================================== attention needed */
function NeedsAttention({ s }: { s: Snapshot }) {
  const items = s.brief?.items ?? []
  return (
    <div style={{ maxHeight: 460, overflow: 'auto', marginRight: -8, paddingRight: 8 }}>
      <FindingList items={items.slice(0, 8)} compact empty={<Empty title="Nothing needs you right now.">Findings appear here when a monitor escalates.</Empty>} />
    </div>
  )
}

/* ================================================================== questions */
function Questions({ s }: { s: Snapshot }) {
  const [text, setText] = useState('')
  const select = useStore((x) => x.selectInvestigation)
  const qs = [...s.questions].reverse()
  const open = qs.filter((q) => q.status !== 'answered').slice(0, 6)
  const answered = qs.filter((q) => q.status === 'answered').slice(0, 4)
  const invFor = (qid: string) => s.investigations.find((i) => i.question_id === qid)
  return (
    <div>
      <form className="row" style={{ marginBottom: 10 }} onSubmit={(e) => { e.preventDefault(); if (text.trim()) { api.question(text.trim()); setText('') } }}>
        <input className="input" placeholder="Ask the swarm a question…" value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn primary" type="submit">Ask</button>
      </form>
      {!open.length && !answered.length && <Empty title="No open questions.">The Executive turns uncertainty into questions here.</Empty>}
      {open.map((q) => (
        <div key={q.id} className="list-item clickable" style={{ borderRadius: 6 }} onClick={() => invFor(q.id) && select(invFor(q.id)!.id)}>
          <div className="row" style={{ alignItems: 'flex-start' }}>
            <span className="node-icon ni-running" style={{ marginTop: 2, width: 14, height: 14 }} />
            <div style={{ flex: 1 }}>
              <div className="serif" style={{ fontSize: 15.5 }}>{q.text}</div>
              <div className="mono muted">{q.status}{q.blocked_reason ? ` · ${q.blocked_reason}` : ''} · {q.requested_by}</div>
            </div>
            <span className="chip soft" style={{ color: q.priority === 'high' ? 'var(--lv-alert)' : 'var(--ink-3)' }}>{q.priority}</span>
          </div>
        </div>
      ))}
      {answered.length > 0 && <div className="label" style={{ margin: '12px 0 2px' }}>Recently answered</div>}
      {answered.map((q) => (
        <div key={q.id} className="list-item clickable" style={{ borderRadius: 6 }} onClick={() => invFor(q.id) && select(invFor(q.id)!.id)}>
          <div style={{ fontSize: 13, color: 'var(--ink-2)' }}>{q.text}</div>
          <div className="italic" style={{ fontSize: 14.5, marginTop: 2 }}>{q.answer?.text}</div>
        </div>
      ))}
    </div>
  )
}

/* ================================================================== monitor attention */
function MonitorAttention({ s }: { s: Snapshot }) {
  const rows = s.attention.by_scope.slice(0, 8)
  const max = Math.max(1, ...rows.map((r) => r.tokens || r.calls))
  if (!rows.length) return <Empty title="No monitoring effort spent yet." />
  return (
    <table className="t">
      <thead><tr><th>Where attention goes</th><th className="num" title="monitors">mon</th><th className="num" title="investigator calls">inv</th><th style={{ width: '34%' }}>effort</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.scope}>
            <td>
              <div className="row" style={{ gap: 6 }}>
                {r.focus > 0 && <span title={`Executive focus, weight ${r.focus}`} className="live-dot" style={{ background: 'var(--ink)', boxShadow: 'none', width: 6, height: 6 }} />}
                <ScopeLink scope={r.scope} label={r.label} />
              </div>
            </td>
            <td className="num">{r.monitors.length}</td>
            <td className="num">{r.investigators}</td>
            <td title={`${r.calls} calls · ${fmtNum(r.tokens)} tokens${s.health.llm_mode === 'stub' ? ' (estimated)' : ''}`}>
              <Bar value={r.tokens || r.calls} max={max} color={r.focus > 0 ? 'var(--accent)' : 'var(--ink-4)'} />
              <div className="mono muted" style={{ fontSize: 10, whiteSpace: 'nowrap' }}>{r.calls} calls · {fmtNum(r.tokens)} tok</div></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/* ================================================================== health */
function Health({ s }: { s: Snapshot }) {
  const h = s.health
  const mons = Object.entries(h.monitors)
  const quality = (v: number) => (v >= 0.3 ? 'good' : v >= 0.12 ? 'fair' : 'thin')
  return (
    <div className="stack">
      <div className="kv" style={{ alignItems: 'center' }}>
        <span className="label"><Term k="coverage" /></span>
        <span className="row" style={{ gap: 8 }}><span style={{ flex: 1 }}><Bar value={h.coverage} color="var(--st-observed)" /></span><span className="mono">{pct(h.coverage)} · {quality(h.coverage)}</span></span>
        <span className="label"><Term k="disagreement" /></span><span className="mono">{h.disagreement == null ? 'not measured (one evaluator per finding)' : pct(h.disagreement)}</span>
        <span className="label"><Term k="blind_spots" /></span><span className="mono">{h.blind_spots}</span>
        <span className="label">model spend</span><span className="mono">${h.spent_usd.toFixed(2)}{h.llm_mode === 'stub' ? ' · models off' : ` · ${h.llm_mode}`}</span>
      </div>
      <hr className="soft" style={{ margin: '4px 0' }} />
      {mons.map(([id, m]) => (
        <div key={id} className="row" style={{ justifyContent: 'space-between' }}>
          <span>{id}</span>
          <span className="row" style={{ gap: 8 }}><span className="mono muted">{m.reports} reports</span><LevelChip level={m.level} /></span>
        </div>
      ))}
      {s.executive.blind_spots.length > 0 && <div className="italic muted" style={{ fontSize: 14 }}>{s.executive.blind_spots[0]}</div>}
      {h.errors.length > 0 && <div className="mono" style={{ color: 'var(--st-contradicted)', fontSize: 11 }}>{h.errors[h.errors.length - 1].slice(0, 200)}</div>}
    </div>
  )
}

/* ================================================================== investigations mini */
const NODE_GLYPH: Record<string, string> = { done: '✓', partial: '◐', running: '◐', pending: '', stopped: '–', failed: '!' }
function InvestigationsMini({ s }: { s: Snapshot }) {
  const select = useStore((x) => x.selectInvestigation)
  const invs = [...s.investigations].reverse().slice(0, 4)
  if (!invs.length) return <Empty title="No investigations yet.">When something deserves more cognition, a tree grows here.</Empty>
  return (
    <div className="grid" style={{ gridTemplateColumns: `repeat(${Math.min(invs.length, 2)}, minmax(0, 1fr))`, gap: 12 }}>
      {invs.map((inv) => (
        <div key={inv.id} className="card clickable" onClick={() => select(inv.id)}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="label">{inv.status}</span><span className="mono muted">{fmtTime(inv.opened, true)}</span>
          </div>
          <div className="serif" style={{ fontSize: 15, margin: '4px 0 8px', lineHeight: 1.3 }}>{inv.title}</div>
          <div className="stack" style={{ gap: 4 }}>
            {inv.nodes.map((n) => (
              <div key={n.id} className="row" style={{ gap: 7 }}>
                <span className={`node-icon ni-${n.status}`} style={{ width: 16, height: 16, fontSize: 9 }}>{NODE_GLYPH[n.status]}</span>
                <span style={{ fontSize: 12.5, color: n.status === 'pending' ? 'var(--ink-3)' : 'var(--ink-2)' }}>{n.title}</span>
              </div>
            ))}
          </div>
          {inv.conclusion && <div className="italic clamp-3" style={{ fontSize: 14, marginTop: 8, color: 'var(--ink)' }}>{inv.conclusion}</div>}
        </div>
      ))}
    </div>
  )
}

/* ================================================================== executive context */
function ExecutiveContext({ s }: { s: Snapshot }) {
  const [pinText, setPin] = useState('')
  const e = s.executive
  const pending = s.directives.filter((d) => d.status === 'proposed')
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div>
        <div className="label" style={{ marginBottom: 4 }}>Hypotheses</div>
        {!e.hypotheses.length && <div className="muted" style={{ fontSize: 13 }}>None yet.</div>}
        {e.hypotheses.slice(-4).reverse().map((h) => (
          <div key={h.id} className="row" style={{ alignItems: 'flex-start', padding: '4px 0' }}>
            <span className="chip soft" style={{ color: h.status === 'supported' ? 'var(--st-observed)' : h.status === 'weakened' ? 'var(--st-contradicted)' : 'var(--st-inferred)' }}>{h.status}</span>
            <span className="clamp-3" style={{ fontSize: 13, flex: 1 }}>{h.text}</span>
            <span className="mono muted">{pct(h.confidence)}</span>
          </div>
        ))}
      </div>
      <div>
        <div className="row" style={{ marginBottom: 4 }}><span className="label">What it keeps in mind</span><span className="mono muted" style={{ marginLeft: 'auto' }}>v{s.ledger.version} · {s.ledger.entries.length} entries</span></div>
        {s.ledger.entries.slice(-6).reverse().map((l) => (
          <div key={l.id} className="row" style={{ alignItems: 'flex-start', padding: '3px 0' }}>
            <span className="mono muted" style={{ minWidth: 92, fontSize: 10.5 }}>{l.kind.replace('_', ' ')}</span>
            <span style={{ fontSize: 12.5, flex: 1, color: 'var(--ink-2)' }}>{l.text}</span>
            {l.pinned_by === 'human' ? <button className="btn ghost sm" title="Unpin" onClick={() => api.unpin(l.id)}><Icon name="x" size={12} /></button>
              : <span className="mono muted" style={{ fontSize: 10 }}>exec</span>}
          </div>
        ))}
        <form className="row" style={{ marginTop: 6 }} onSubmit={(ev) => { ev.preventDefault(); if (pinText.trim()) { api.pin(pinText.trim(), 'human_instruction'); setPin('') } }}>
          <input className="input" placeholder="Pin an instruction or fact for the analysts…" value={pinText} onChange={(ev) => setPin(ev.target.value)} />
          <button className="btn" type="submit"><Icon name="pin" size={14} />Pin</button>
        </form>
      </div>
      {pending.length > 0 && (
        <div>
          <div className="label" style={{ marginBottom: 4 }}>Suggestions awaiting you</div>
          {pending.slice(-4).map((d) => (
            <div key={d.id} className="row card" style={{ marginBottom: 6, padding: 8 }}>
              <span className="chip soft" style={{ color: 'var(--accent)' }}>{d.kind}</span>
              <span style={{ fontSize: 12.5, flex: 1 }}><ScopeLink scope={d.scope} /> — {d.reason}</span>
              <button className="btn sm" onClick={() => api.approve(d.id, true)}>Apply</button>
              <button className="btn ghost sm" onClick={() => api.approve(d.id, false)}>Reject</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ================================================================== data-driven panels */
function TimelinePanel() {
  const d = useView<TimelineData>('activity_timeline')
  if (d && !d.buckets.some((b) => b.total)) return <Empty title="No activity yet.">Press play to replay, or wait for live agents to report.</Empty>
  return <StackedTimeline data={d} height={250} />
}
function PopulationPanel() {
  const [hours, setHours] = useState(12)
  const d = useView<GraphData>('actor_resource_graph', { hours }, 2)
  return (
    <div>
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: -30, marginBottom: 6 }}>
        <div className="seg">{[3, 12, 48].map((h) => <button key={h} className={h === hours ? 'on' : ''} onClick={() => setHours(h)}>{h}h</button>)}</div>
      </div>
      {d && !d.nodes.length ? <Empty title="No shared resources in this window." /> : <Bipartite data={d} />}
    </div>
  )
}
function SwimlanePanel() {
  const d = useView<SwimData>('actor_swimlane', { hours: 10 }, 2)
  return d && !d.lanes.length ? <Empty title="No agent activity yet." /> : <Swimlanes data={d} />
}
function LineagePanel() {
  const d = useView<{ chains: LineageChain[] }>('artifact_lineage', {}, 2)
  if (!d || !d.chains.length) return <Empty title="No reused content yet.">Content reused across agents shows its path here.</Empty>
  return <Lineage chains={d.chains.slice(0, 4)} />
}
function SayDoPanel() {
  const d = useView<{ rows: any[]; uncorroborated: number; total: number }>('say_vs_do', {}, 2)
  const open = useStore((x) => x.openDrawer)
  if (!d || !d.rows.length) return <Empty title="No completion claims yet.">When agents report finished work, we check it against what they did.</Empty>
  return (
    <div>
      <div className="row" style={{ marginBottom: 8, gap: 16 }}>
        <span><span className="display" style={{ fontSize: 26 }}>{d.uncorroborated}</span> <span className="muted">uncorroborated</span></span>
        <span className="muted">of {d.total} claims of completed work</span>
      </div>
      <table className="t"><tbody>
        {d.rows.slice(0, 7).map((r) => (
          <tr key={r.event} className="clickable" onClick={() => open({ kind: 'event', id: r.event })}>
            <td className="mono muted" style={{ width: 54 }}>{fmtTime(r.ts)}</td>
            <td><span style={{ fontWeight: 500 }}>{r.third_party ? 'Summary' : r.actor}</span> <span className="muted">says “{r.claim.replace('_', ' ')}”</span></td>
            <td style={{ width: 130 }}>{r.status === 'corroborated'
              ? <span className="chip soft st-OBSERVED"><span className="dot" />{r.corroborating} actions</span>
              : <span className="chip soft st-CONTRADICTED"><span className="dot" />not in record</span>}</td>
          </tr>
        ))}
      </tbody></table>
    </div>
  )
}
function EventTable({ view, params = {} }: { view: string; params?: Record<string, string | number> }) {
  const d = useView<{ events: any[] }>(view, params)
  const open = useStore((x) => x.openDrawer)
  if (!d || !d.events.length) return <Empty title="Nothing here yet." />
  return (
    <div style={{ maxHeight: 360, overflow: 'auto' }}>
      <table className="t"><tbody>
        {d.events.map((e) => (
          <tr key={e.id} className="clickable" onClick={() => open({ kind: 'event', id: e.id })}>
            <td className="mono muted" style={{ width: 50 }}>{fmtTime(e.ts)}</td>
            <td style={{ width: 4, padding: 0 }}><span style={{ display: 'block', width: 3, height: 18, borderRadius: 2, background: famColor(e.family) }} /></td>
            <td style={{ fontWeight: 500, whiteSpace: 'nowrap' }}>{e.actor}</td>
            <td className="mono muted" style={{ whiteSpace: 'nowrap' }}>{e.action}</td>
            <td className="ink2" style={{ fontSize: 12.5 }}>{e.object}{e.note ? <span className="muted"> · {String(e.note).slice(0, 70)}</span> : null}</td>
          </tr>
        ))}
      </tbody></table>
    </div>
  )
}
function Workstreams({ s }: { s: Snapshot }) {
  const ws = s.executive.workstreams
  if (!ws.length) return <Empty title="No workstreams yet." />
  const max = Math.max(1, ...ws.map((w) => w.events))
  const arrow = (t: string) => (t === 'rising' ? '↗' : t === 'falling' ? '↘' : t === 'new' ? '✦' : '→')
  return (
    <div className="stack" style={{ gap: 8 }}>
      {ws.map((w) => (
        <div key={w.id}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="row" style={{ gap: 7 }}><i style={{ width: 9, height: 9, borderRadius: 3, background: famColor(w.label), display: 'inline-block' }} />{w.label}</span>
            <span className="mono muted">{arrow(w.trend)} {w.trend} · {w.events}</span>
          </div>
          <Bar value={w.events} max={max} color={famColor(w.label)} />
        </div>
      ))}
    </div>
  )
}
function ControlMini({ s }: { s: Snapshot }) {
  const setRoute = useStore((x) => x.setRoute)
  const c = s.control
  if (!c) return <Empty title="Historical replay.">Control is available for live swarms.</Empty>
  return (
    <div className="stack">
      <div className="row" style={{ gap: 14 }}>
        <span><span className="display" style={{ fontSize: 28 }}>{c.agents}</span> <span className="muted">agents</span></span>
        {Object.entries(c.statuses).map(([k, v]) => <span key={k} className="mono muted">{k} {v}</span>)}
      </div>
      {c.pending.map((p) => (
        <div key={p.id} className="card row" style={{ borderColor: 'var(--lv-alert)' }}>
          <LevelChip level="ALERT" />
          <span style={{ flex: 1, fontSize: 13 }}><b>{p.label}</b> wants <span className="mono">{p.tool}</span>: {p.input.slice(0, 70)}</span>
          <button className="btn sm" onClick={() => api.control('allow', p.id)}>Allow</button>
          <button className="btn sm danger" onClick={() => api.control('deny', p.id)}>Deny</button>
        </div>
      ))}
      <button className="btn" onClick={() => setRoute('control')}>Open control <Icon name="arrow" size={14} /></button>
    </div>
  )
}

/* ================================================================== registry */
export const PANELS: PanelDef[] = [
  { id: 'brief', title: 'Live brief', blurb: 'What SwarmFrame noticed, newest first', requires: [], span: 5, defaultOn: true, question: 'changed',
    render: (s) => <LiveBrief s={s} /> },
  { id: 'organization', title: 'The analyst team', blurb: 'The AI analysts reading the swarm, and how they are split up', requires: [], span: 5, defaultOn: false, question: 'unknown',
    render: (s) => <OrgMini s={s} /> },
  { id: 'population', title: 'Who works on what', blurb: 'Agents and the shared resources they touch; findings ringed', requires: ['identities', 'resources'], span: 7, defaultOn: true, question: 'happening',
    render: () => <PopulationPanel /> },
  { id: 'timeline', title: 'Activity by workstream', blurb: 'Stacked activity with briefing markers', requires: ['timestamps'], span: 7, defaultOn: true, question: 'happening',
    render: () => <TimelinePanel /> },
  { id: 'attention', title: 'Needs attention', blurb: 'Findings ranked by severity, each with a next step', requires: [], span: 5, defaultOn: true, question: 'attention',
    render: (s) => <NeedsAttention s={s} />, kicker: (s) => `${s.brief?.items.length ?? 0} findings` },
  { id: 'questions', title: 'Open questions', blurb: 'What SwarmFrame does not understand yet; ask your own', requires: [], span: 5, defaultOn: true, question: 'unknown',
    render: (s) => <Questions s={s} /> },
  { id: 'investigations', title: 'Investigations', blurb: 'Focused looks at single findings', requires: [], span: 7, defaultOn: true, question: 'unknown',
    render: (s) => <InvestigationsMini s={s} /> },
  { id: 'monitor_attention', title: 'Where monitoring effort goes', blurb: 'Which scopes the monitors spend their reading on', requires: [], span: 4, defaultOn: false, question: 'attention',
    render: (s) => <MonitorAttention s={s} /> },
  { id: 'executive', title: 'What SwarmFrame believes', blurb: 'Hypotheses, what it keeps in mind, suggestions awaiting you', requires: [], span: 4, defaultOn: false, question: 'unknown',
    render: (s) => <ExecutiveContext s={s} /> },
  { id: 'health', title: 'Monitor health', blurb: 'How much is read closely, where analysts disagree, what nobody has read', requires: [], span: 4, defaultOn: false, question: 'unknown',
    render: (s) => <Health s={s} /> },
  { id: 'say_do', title: 'Said vs did', blurb: 'Claims of finished work, checked against what the agents actually did', requires: ['self_reports'], span: 6, defaultOn: true, question: 'attention',
    render: () => <SayDoPanel /> },
  { id: 'lineage', title: 'Content reuse', blurb: 'Content that reappears across agents, and whether we saw how it spread', requires: ['artifacts'], span: 6, defaultOn: false, question: 'changed',
    render: () => <LineagePanel /> },
  { id: 'swimlane', title: 'Agent swimlanes', blurb: 'Each agent’s recent work, colored by workstream', requires: ['identities', 'timestamps'], span: 12, defaultOn: false, question: 'happening',
    render: () => <SwimlanePanel /> },
  { id: 'workstreams', title: 'Workstreams', blurb: 'What the population is working on, and the trend', requires: [], span: 4, defaultOn: false, question: 'happening',
    render: (s) => <Workstreams s={s} /> },
  { id: 'environment', title: 'Environment & humans', blurb: 'Operator actions, denials, human messages', requires: ['environment'], span: 6, defaultOn: false, question: 'changed',
    render: () => <EventTable view="environment_feed" /> },
  { id: 'control', title: 'Live control', blurb: 'Agents, approvals waiting for you, operator actions', requires: ['control'], span: 5, defaultOn: true, question: 'control',
    render: (s) => <ControlMini s={s} /> },
  { id: 'triage', title: 'Reading plan', blurb: 'What the analysts read closely this cycle: by priority, longest unread, and random spot-checks', requires: [], span: 7, defaultOn: false, question: 'attention',
    render: (s) => <TriagePanel s={s} /> },
  { id: 'cohorts', title: 'Groups that behave alike', blurb: 'Similar agents grouped together, with how each group changed and who stands out', requires: [], span: 5, defaultOn: false, question: 'happening',
    render: (s) => <CohortsPanel s={s} />, kicker: (s) => s.scale ? `${s.scale.population.cohorts} groups` : '' },
  { id: 'coverage', title: 'What we have read', blurb: 'Which groups got a close look this cycle, and which did not', requires: [], span: 5, defaultOn: false, question: 'unknown',
    render: (s) => <CoveragePanel s={s} /> },
  { id: 'templates', title: 'Message types', blurb: 'Kinds of agent text (wording hidden), and how far each spread', requires: ['artifacts'], span: 6, defaultOn: false, question: 'changed',
    render: (s) => <TemplatesPanel s={s} /> },
  { id: 'world', title: 'The World', blurb: 'The swarm in 3D: units stand near what they work on and whom they work with', requires: [], span: 12, defaultOn: false, question: 'happening',
    render: () => <React.Suspense fallback={<div className="skeleton" style={{ height: 340 }} />}><WorldMini /></React.Suspense> },
  { id: 'feed', title: 'Raw event stream', blurb: 'Every evidence event, newest first', requires: [], span: 12, defaultOn: false, question: 'happening',
    render: () => <EventTable view="event_feed" params={{ n: 80 }} /> },
]

export function available(p: PanelDef, caps: Record<string, { present: boolean }> | undefined): { ok: boolean; missing: string[] } {
  const missing = p.requires.filter((r) => !caps?.[r]?.present)
  return { ok: missing.length === 0, missing }
}
