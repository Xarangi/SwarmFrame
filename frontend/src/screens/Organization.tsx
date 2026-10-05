import React, { useEffect, useMemo, useState } from 'react'
import { get, post } from '../api'
import { useStore } from '../store'
import type { Snapshot } from '../types'
import { Bar, Empty, fmtTime, Icon, Panel, Seg, StatusChip, Toggle } from '../components/ui'

interface OrgNode {
  id: string; role: string; title: string; parent: string | null; scope: string; scope_label: string; brief: string
  status: string; depth: number; runs: number; cost_usd: number; tokens: number; last_run: string | null
  last_headline: string; last_status: string; children: string[]; spawned_by: string; backend: string | null
  model: string | null; error: string | null; retired_reason: string | null; notes: string
  report: { headline: string; summary: string; claims: { id: string; status: any; statement: string }[]; flags: any[]; recommend: any; open_points: string[] } | null
}
interface OrgSnap {
  topology: { id: string; title: string; description: string; root: string; roles: Record<string, any>; scaling: any; divisions: any; maintain: any; cycle: string[] }
  cycle: number; running: boolean; root: string | null
  budget: { spent_total: number; spent_cycle: number; total: number; per_cycle: number }
  nodes: OrgNode[]; divisions: any[]; events: { id: string; ts: string; kind: string; node: string | null; by: string; text: string }[]
  runs: any[]; backend_mode: string
}

const STATUS_COLOR: Record<string, string> = {
  concerning: 'var(--lv-alert)', notable: 'var(--lv-investigate)', normal: 'var(--st-observed)', quiet: 'var(--ink-4)',
  supported: 'var(--st-observed)', partially_supported: 'var(--st-inferred)', unsupported: 'var(--st-contradicted)', unknown: 'var(--ink-4)',
}

function useOrg(): [OrgSnap | null, () => void] {
  const tick = useStore((s) => s.tick)
  const [d, set] = useState<OrgSnap | null>(null)
  const load = () => { get<OrgSnap>('/api/agents').then(set).catch(() => {}) }
  useEffect(load, [tick])
  return [d, load]
}

export function roleColor(roles: string[], role: string): string {
  const i = roles.indexOf(role)
  return i < 0 ? 'var(--c-other)' : `var(--c${[1, 2, 5, 4, 6, 3, 7, 8][i % 8]})`
}

export function Organization({ s }: { s: Snapshot }) {
  const [tab, setTab] = useState<'team' | 'topology'>('team')
  const [org, reload] = useOrg()
  return (
    <div className="fade-in">
      <div className="row" style={{ alignItems: 'flex-end', marginBottom: 6, gap: 14 }}>
        <div>
          <div className="page-title">The analyst team</div>
          <div className="muted" style={{ maxWidth: 780 }}>
            A main agent steers a team of structured readers whose roles, partition and rules come from the team shape below.
            Everything about the team is defined by a topology you can edit.
          </div>
        </div>
        <div style={{ marginLeft: 'auto' }}>
          <Seg value={tab} onChange={setTab} options={[{ v: 'team', l: 'Live team' }, { v: 'topology', l: 'Topology' }]} />
        </div>
      </div>
      {!org ? null : tab === 'team' ? <Team org={org} reload={reload} /> : <TopologyEditor onApplied={reload} />}
    </div>
  )
}

/* ================================================================== the team choice: who picked this shape, and why */
function TeamChoice({ reload }: { reload: () => void }) {
  const team = useStore((s) => s.snap?.team)
  const [lib, setLib] = useState<{ id: string; title: string; description: string }[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => { fetch('/api/agents/topologies').then((r) => r.json()).then((d) => setLib(d.topologies ?? [])).catch(() => {}) }, [])
  if (!team) return null
  const BY: Record<string, string> = { override: 'chosen for this session', pack: 'named by the source pack', selector: 'chosen from the stream\'s shape', default: 'the org config\'s default', human: 'switched here' }
  const switchTo = async (id: string) => {
    if (!id || id === team.topology) return
    setBusy(true)
    try { await fetch('/api/agents/topology', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ select: id }) }); reload() } finally { setBusy(false) }
  }
  const part = team.partition?.by ? `${team.partition.by}${team.partition.field ? ` · ${team.partition.field}` : ''}` : 'cohorts'
  return (
    <div className="team-choice">
      <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <span className="chip soft" style={{ color: 'var(--st-derived)' }}>{BY[team.by] ?? team.by}</span>
        <span style={{ fontSize: 13 }}>{team.reasons.join('; ')}</span>
      </div>
      {team.would_pick && team.would_pick !== team.topology && (
        <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>From the stream's shape alone SwarmFrame would pick <b>{team.would_pick}</b>: {team.would_pick_reasons.join('; ')}</div>
      )}
      <div className="row mono muted" style={{ gap: 14, marginTop: 6, fontSize: 11.5, flexWrap: 'wrap' }}>
        <span>partition · {part}</span>
        {team.levels?.length > 0 && <span>levels · {team.levels.map((l: any) => `${l.role} (span ${l.span})`).join(', ')}</span>}
        {team.standing?.length > 0 && <span>standing · {team.standing.map((s: any) => s.role).join(', ')}</span>}
        {team.cadence?.kind && <span>cycle · every {team.cadence.every} {team.cadence.kind}</span>}
        {team.human?.interrupt_at && <span>interrupt a person at · {team.human.interrupt_at.toLowerCase()}</span>}
        {team.authority?.alerts_per_cycle != null && <span>alerts per cycle · {team.authority.alerts_per_cycle}</span>}
        {team.shape?.identity && <span>stream · identities {team.shape.identity}, {team.shape.population} units, {team.shape.cohorts} cohorts</span>}
      </div>
      <div className="row" style={{ gap: 8, marginTop: 8, alignItems: 'center' }}>
        <span className="label">Switch team</span>
        <select className="input" value={team.topology} disabled={busy} onChange={(e) => switchTo(e.target.value)} style={{ maxWidth: 420 }}>
          {lib.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
        </select>
      </div>
    </div>
  )
}

/* ================================================================== proposals: how the team asked to change itself */
function Proposals({ reload }: { reload: () => void }) {
  const ap = useStore((s) => s.snap?.approvals)
  const team = useStore((s) => s.snap?.team)
  const [busy, setBusy] = useState(false)
  if (!ap) return null
  const act = async (id: string, action: string) => {
    setBusy(true)
    try { await fetch(`/api/agents/proposal/${encodeURIComponent(id)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) }); reload() } finally { setBusy(false) }
  }
  const promote = async () => {
    setBusy(true)
    try { const r = await fetch('/api/agents/promote', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); const d = await r.json(); useStore.getState().showToast(r.ok ? `Saved as preset ${d.topology}` : (d.detail ?? 'could not promote')); reload() } finally { setBusy(false) }
  }
  const COLOR: Record<string, string> = { pending: 'var(--st-derived)', approved: 'var(--st-derived)', applied: 'var(--st-observed)', declined: 'var(--ink-3)', failed: 'var(--st-contradicted)', reverted: 'var(--ink-3)' }
  return (
    <Panel title="Proposals" className="span-12" kicker={`${ap.count} waiting · the team may act alone within its envelope (${ap.envelope.approval === 'always_human' ? 'nothing without you' : `reading roles on ${String(ap.envelope.max_model).replace('claude-', '')} or below, no raw text`})`}
      right={<button className="btn sm" disabled={busy} onClick={promote} title="Save the running team as a topology and make it this source's preset"><Icon name="pin" size={13} />Save as this source's preset{team ? ` (${team.topology})` : ''}</button>}>
      {ap.recent.length === 0 && <Empty title="No proposals yet.">When the team wants to change its own shape (a new role, a different partition), it appears here and, if it needs you, on the Brief.</Empty>}
      <div className="stack" style={{ gap: 6 }}>
        {[...ap.recent].reverse().map((p) => (
          <div key={p.id} className="row" style={{ gap: 10, alignItems: 'flex-start', padding: '6px 4px', borderTop: '1px solid var(--line)' }}>
            <span className="chip soft" style={{ color: COLOR[p.status] ?? 'var(--ink-3)', minWidth: 70, justifyContent: 'center' }}>{p.status}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13.5 }}><b>{p.describe}</b> <span className="muted">· {p.by}</span></div>
              <div className="muted" style={{ fontSize: 12.5 }}>{p.reasons.join('; ')}{p.note ? ` — ${p.note}` : ''}</div>
            </div>
            <span className="row" style={{ gap: 6 }}>
              {p.status === 'pending' && <><button className="btn sm accent" disabled={busy} onClick={() => act(p.id, 'approve')}>Approve</button><button className="btn sm ghost" disabled={busy} onClick={() => act(p.id, 'decline')}>Decline</button></>}
              {p.status === 'applied' && <button className="btn sm ghost" disabled={busy} onClick={() => act(p.id, 'revert')}>Revert</button>}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  )
}

/* ================================================================== the delegation log: who fired off what, and why */
function DelegationLog() {
  const d = useStore((s) => s.snap?.delegations)
  const [kind, setKind] = useState<string>('all')
  if (!d) return null
  const rows = [...d.recent].reverse().filter((r) => kind === 'all' || r.kind === kind)
  const KIND: Record<string, [string, string]> = { native: ['fired a sub-agent', 'var(--accent)'], managed: ['spawned', 'var(--st-derived)'], rerun: ['re-tasked', 'var(--st-derived)'],
    retire: ['retired', 'var(--ink-3)'], escalation: ['escalated', 'var(--lv-alert)'], proposal: ['proposed', 'var(--st-self)'], note: ['noted', 'var(--ink-3)'] }
  return (
    <Panel title="Delegation log" className="span-12" kicker={`${d.total} entries · ${Object.entries(d.by_kind).map(([k, n]) => `${n} ${KIND[k]?.[0] ?? k}`).join(' · ')}`}
      right={<span className="row" style={{ gap: 8, alignItems: 'center' }}>
        <select className="input" value={kind} onChange={(e) => setKind(e.target.value)} style={{ fontSize: 12 }}>
          <option value="all">all kinds</option>{Object.keys(KIND).map((k) => <option key={k} value={k}>{KIND[k][0]}</option>)}
        </select>
        <span className="mono muted" title={d.path} style={{ fontSize: 11 }}>also a file: …{d.path.replace(/\\/g, '/').split('/').slice(-3).join('/')}</span>
      </span>}>
      {rows.length === 0 && <Empty title="Nothing delegated yet.">Every sub-agent an agent fires off, every spawn, re-task, retirement and escalation lands here with its reason.</Empty>}
      <div className="stack" style={{ gap: 4 }}>
        {rows.map((r, i) => (
          <div key={i} className="row" style={{ gap: 10, alignItems: 'flex-start', padding: '5px 4px', borderTop: '1px solid var(--line)', fontSize: 13 }}>
            <span className="mono muted" style={{ minWidth: 86, fontSize: 11.5 }}>{r.stream_ts.replace('T', ' ')}</span>
            <span className="chip soft" style={{ color: KIND[r.kind]?.[1] ?? 'var(--ink-3)', minWidth: 110, justifyContent: 'center' }}>{KIND[r.kind]?.[0] ?? r.kind}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div><b>{r.by}</b>{r.target ? <span className="muted"> → {r.target}</span> : null}{r.why ? <span>: {r.why}</span> : null}</div>
              {r.brief && <div className="muted" style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>{r.brief}</div>}
              {r.outcome && <div style={{ fontSize: 12, color: 'var(--st-observed)' }}>↳ {r.outcome}</div>}
            </div>
            {r.cost_usd > 0 && <span className="mono muted" style={{ fontSize: 11 }}>${r.cost_usd.toFixed(3)}</span>}
          </div>
        ))}
      </div>
    </Panel>
  )
}

/* ================================================================== live team */
function Team({ org, reload }: { org: OrgSnap; reload: () => void }) {
  const [sel, setSel] = useState<string | null>(null)
  const [showRetired, setShowRetired] = useState(false)
  const roles = Object.keys(org.topology.roles)
  const nodes = org.nodes.filter((n) => showRetired || n.status !== 'retired')
  const byId = useMemo(() => Object.fromEntries(org.nodes.map((n) => [n.id, n])), [org.nodes])
  const roots = nodes.filter((n) => !n.parent || !byId[n.parent] || (!showRetired && byId[n.parent].status === 'retired'))
  const kids = (id: string) => nodes.filter((n) => n.parent === id)
  const active = org.nodes.filter((n) => n.status !== 'retired')
  const counts = roles.map((r) => [r, active.filter((n) => n.role === r).length] as const)
  const selected = sel ? byId[sel] : byId[org.root || ''] ?? null
  const b = org.budget
  return (
    <>
      <section className="hero" style={{ gridTemplateColumns: 'minmax(0,1.4fr) minmax(0,1fr)', padding: '20px 24px' }}>
        <div>
          <div className="row" style={{ gap: 10 }}>
            <span className="label">Topology</span><span className="mono muted">{org.topology.id}</span>
            {org.running && <span className="chip soft" style={{ color: 'var(--st-inferred)' }}><span className="dot" />cycle running</span>}
          </div>
          <div className="display" style={{ fontSize: 26, margin: '6px 0 4px' }}>{org.topology.title}</div>
          <div className="muted" style={{ fontSize: 13.5 }}>{org.topology.description}</div>
          <TeamChoice reload={reload} />
          <div className="row" style={{ gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
            {counts.map(([r, n]) => (
              <span key={r} className="chip soft" style={{ color: roleColor(roles, r), textTransform: 'none', letterSpacing: 0 }}>
                <span className="dot" />{n} {org.topology.roles[r].title.toLowerCase()}{n === 1 ? '' : 's'}
              </span>
            ))}
          </div>
        </div>
        <div className="stats">
          <div className="stat"><div className="v">{org.cycle}</div><div className="label k">cycles run</div></div>
          <div className="stat"><div className="v">{org.divisions.length}</div><div className="label k">divisions</div></div>
          <div className="stat" style={{ gridColumn: 'span 2' }}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span className="label">spend · {org.backend_mode === 'stub' ? 'deterministic, free' : org.backend_mode}</span>
              <span className="mono">${b.spent_total.toFixed(3)} / ${Number(b.total).toFixed(2)}</span>
            </div>
            <div style={{ margin: '8px 0 4px' }}><Bar value={b.spent_total} max={Number(b.total) || 1} color="var(--accent)" /></div>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <span className="mono muted">this cycle ${b.spent_cycle.toFixed(3)} of ${Number(b.per_cycle).toFixed(2)}</span>
              <button className="btn sm" disabled={org.running} onClick={() => post('/api/agents/action', { action: 'cycle' }).then(reload)}>
                <Icon name="play" size={12} />Run a cycle now</button>
            </div>
          </div>
        </div>
      </section>

      <div className="grid">
        <Panel title="Team" className="span-7" kicker={`${active.length} active`}
          right={<label className="row mono muted" style={{ gap: 6 }}>retired <Toggle on={showRetired} onChange={setShowRetired} /></label>}>
          {!roots.length ? <Empty title="No agents yet.">The main agent spawns its team on the first cycle. Press play, or run a cycle now.</Empty> : (
            <div className="tree" style={{ maxHeight: 720, overflow: 'auto', marginRight: -8, paddingRight: 8 }}>
              {roots.map((n) => <AgentCard key={n.id} n={n} kids={kids} roles={roles} sel={selected?.id} onSel={setSel} org={org} top />)}
            </div>
          )}
        </Panel>
        <div className="span-5 stack" style={{ gap: 16 }}>
          {selected && <AgentDetail key={selected.id} n={selected} org={org} roles={roles} reload={reload} />}
        </div>
        <Panel title="Divisions" className="span-7" kicker={`strategy: ${org.topology.divisions.strategy}`}>
          <Divisions org={org} reload={reload} onSel={setSel} />
        </Panel>
        <Proposals reload={reload} />
        <DelegationLog />
        <Panel title="What the organization did" className="span-5">
          <div style={{ maxHeight: 380, overflow: 'auto' }}>
            {[...org.events].reverse().filter((e) => e.kind !== 'run').slice(0, 60).map((e) => (
              <div key={e.id} className="row" style={{ alignItems: 'flex-start', padding: '5px 0', borderTop: '1px solid var(--line-2)' }}>
                <span className="mono muted" style={{ width: 44 }}>{fmtTime(e.ts)}</span>
                <span className="chip soft" style={{ color: EVENT_COLOR[e.kind] ?? 'var(--ink-3)', minWidth: 58, justifyContent: 'center' }}>{e.kind}</span>
                <span style={{ fontSize: 12.5, flex: 1, color: 'var(--ink-2)' }}>{e.text}</span>
                <span className="mono muted" style={{ fontSize: 10 }}>{e.by === 'system' ? '' : e.by.startsWith('ag_') ? (org.nodes.find((n) => n.id === e.by)?.role ?? 'agent') : e.by}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  )
}
const EVENT_COLOR: Record<string, string> = { spawn: 'var(--st-observed)', retire: 'var(--ink-3)', split: 'var(--st-derived)', merge: 'var(--st-derived)',
  define: 'var(--st-derived)', cycle: 'var(--accent)', budget: 'var(--lv-alert)', error: 'var(--st-contradicted)', topology: 'var(--st-self)' }

function AgentCard({ n, kids, roles, sel, onSel, org, top = false }: {
  n: OrgNode; kids: (id: string) => OrgNode[]; roles: string[]; sel?: string; onSel: (id: string) => void; org: OrgSnap; top?: boolean
}) {
  const children = kids(n.id)
  const color = roleColor(roles, n.role)
  const roleTitle = org.topology.roles[n.role]?.title ?? n.role
  const card = (
    <button className="node-card" onClick={() => onSel(n.id)}
      style={{ width: '100%', textAlign: 'left', cursor: 'pointer', borderColor: sel === n.id ? 'var(--ink)' : undefined,
        opacity: n.status === 'retired' ? 0.5 : 1, borderLeft: `3px solid ${color}`, padding: top ? '14px 16px' : undefined }}>
      <div className="row" style={{ gap: 8 }}>
        <span className={`live-dot ${n.status === 'running' ? 'run' : n.status === 'idle' ? '' : 'off'}`}
          style={n.status === 'failed' ? { background: 'var(--st-contradicted)' } : n.status === 'idle' ? { background: color, boxShadow: 'none' } : undefined} />
        <span className="label" style={{ color }}>{roleTitle}</span>
        <span style={{ fontWeight: 600, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.scope === 'population' ? 'whole population' : n.scope_label}</span>
        <span style={{ marginLeft: 'auto' }} className="row">
          {n.last_status && <span className="chip soft" style={{ color: STATUS_COLOR[n.last_status] ?? 'var(--ink-3)' }}>{n.last_status.replace('_', ' ')}</span>}
        </span>
      </div>
      {n.last_headline && <div className={top ? 'display' : 'italic'} style={{ fontSize: top ? 17 : 14, lineHeight: 1.35, marginTop: 6, color: 'var(--ink)' }}>
        {n.last_headline.length > 220 ? n.last_headline.slice(0, 218) + '…' : n.last_headline}</div>}
      <div className="mono muted" style={{ marginTop: 6, fontSize: 10.5 }}>
        {n.runs} run{n.runs === 1 ? '' : 's'} · {n.backend ?? '—'}{n.cost_usd ? ` · $${n.cost_usd.toFixed(3)}` : ''} · last {fmtTime(n.last_run)}
        {children.length ? ` · ${children.length} sub-agent${children.length === 1 ? '' : 's'}` : ''}
        {n.status === 'retired' && n.retired_reason ? ` · retired: ${n.retired_reason}` : ''}
      </div>
    </button>
  )
  return (
    <div className={top ? '' : 'tree-node'}>
      {card}
      {children.length > 0 && <div style={{ marginLeft: top ? 6 : 0 }}>{children.map((c) => <AgentCard key={c.id} n={c} kids={kids} roles={roles} sel={sel} onSel={onSel} org={org} />)}</div>}
    </div>
  )
}

function AgentDetail({ n, org, roles, reload }: { n: OrgNode; org: OrgSnap; roles: string[]; reload: () => void }) {
  const [d, setD] = useState<any>(null)
  const [tab, setTab] = useState<'report' | 'runs' | 'memory' | 'steer'>('report')
  const [task, setTask] = useState('')
  const [spawnRole, setSpawnRole] = useState('')
  const [spawnScope, setSpawnScope] = useState(n.scope)
  const [brief, setBrief] = useState('')
  const [busy, setBusy] = useState(false)
  const openDrawer = useStore((s) => s.openDrawer)
  useEffect(() => { get(`/api/agents/node/${n.id}`).then(setD).catch(() => {}) }, [n.id, n.runs, n.status])
  const role = org.topology.roles[n.role]
  const canSpawn: string[] = role?.can_spawn ?? []
  const act = async (body: Record<string, unknown>) => { setBusy(true); try { await post('/api/agents/action', body); reload() } finally { setBusy(false) } }
  const r = d?.report
  return (
    <section className="panel">
      <div style={{ padding: '16px 18px 6px', borderLeft: `3px solid ${roleColor(roles, n.role)}` }}>
        <div className="row"><span className="label" style={{ color: roleColor(roles, n.role) }}>{role?.title ?? n.role}</span>
          <span className="mono muted" style={{ marginLeft: 'auto' }}>{n.id}</span></div>
        <div className="display" style={{ fontSize: 21, lineHeight: 1.2, margin: '4px 0' }}>{n.scope === 'population' ? 'Whole population' : n.scope_label}</div>
        <div className="muted" style={{ fontSize: 12.5 }}>{role?.description}</div>
        <div className="mono muted" style={{ marginTop: 6 }}>spawned by {n.spawned_by} · {n.model ?? role?.model} · scope {role?.scope}
          {role?.native_subagents?.length ? ` · helpers: ${role.native_subagents.join(', ')}` : ''}</div>
      </div>
      <div style={{ padding: '6px 18px' }}>
        <Seg value={tab} onChange={setTab} options={[{ v: 'report', l: 'Report' }, { v: 'runs', l: `Runs (${n.runs})` }, { v: 'memory', l: 'Brief & memory' }, { v: 'steer', l: 'Steer' }]} />
      </div>
      <div className="panel-body" style={{ maxHeight: 520, overflow: 'auto' }}>
        {tab === 'report' && (!r ? <Empty title="No report yet." /> : (
          <div className="stack" style={{ gap: 10 }}>
            {(r.headline || r.population_state) && <div className="italic" style={{ fontSize: 16.5, lineHeight: 1.4 }}>{r.headline || r.population_state}</div>}
            {r.summary && <div className="ink2" style={{ fontSize: 13 }}>{r.summary}</div>}
            {r.org_rationale && <div className="card" style={{ fontSize: 13 }}><span className="label">Org rationale</span><div>{r.org_rationale}</div></div>}
            {d.claims?.length > 0 && <div>
              <div className="label" style={{ marginBottom: 4 }}>Claims</div>
              {d.claims.map((c: any) => (
                <div key={c.id} className="row clickable" style={{ alignItems: 'flex-start', padding: '3px 4px', borderRadius: 6 }} onClick={() => openDrawer({ kind: 'claim', id: c.id })}>
                  <StatusChip status={c.status} /><span style={{ fontSize: 12.5, flex: 1 }}>{c.statement}</span>
                </div>))}
            </div>}
            {r.flags?.length > 0 && <div>
              <div className="label" style={{ marginBottom: 4 }}>Flags raised</div>
              {r.flags.map((f: any, i: number) => <div key={i} className="row" style={{ fontSize: 12.5, padding: '2px 0' }}>
                <span className="chip soft" style={{ color: f.priority === 'high' || f.priority === 'critical' ? 'var(--lv-alert)' : 'var(--ink-3)' }}>{f.kind}</span>{f.text}</div>)}
            </div>}
            {r.recommend && <div className="mono muted">recommends: {r.recommend.split ? 'split · ' : ''}{r.recommend.specialist ? `specialist (${r.recommend.specialist}) · ` : ''}{r.recommend.retire ? 'retire · ' : ''}{r.recommend.reason || (!r.recommend.split && !r.recommend.specialist && !r.recommend.retire ? 'no change' : '')}</div>}
            {r.open_points?.length > 0 && <div><div className="label">Open points</div>{r.open_points.map((p: string, i: number) => <div key={i} style={{ fontSize: 12.5 }}>· {p}</div>)}</div>}
            {r.org_actions?.length > 0 && <div className="mono muted">org actions: {r.org_actions.map((a: any) => a.action).join(', ')}</div>}
          </div>
        ))}
        {tab === 'runs' && (
          <div className="stack" style={{ gap: 6 }}>
            {!(d?.runs?.length) && <Empty title="Not run yet." />}
            {[...(d?.runs ?? [])].reverse().map((run: any) => (
              <div key={run.id} className="card" style={{ padding: 10 }}>
                <div className="row mono muted" style={{ justifyContent: 'space-between' }}>
                  <span>{fmtTime(run.ts, true)} · {run.backend}{run.model ? ` · ${run.model}` : ''} · by {run.by.startsWith('ag_') ? 'parent' : run.by}</span>
                  <span>{run.seconds}s{run.cost_usd ? ` · $${run.cost_usd.toFixed(3)}` : ''}</span>
                </div>
                {run.task && <div style={{ fontSize: 12.5, marginTop: 3 }}>{run.task}</div>}
                <div className="italic" style={{ fontSize: 13.5, marginTop: 3 }}>{run.headline}</div>
                {run.tool_calls.length > 0 && <div className="row" style={{ gap: 4, flexWrap: 'wrap', marginTop: 5 }}>
                  {run.tool_calls.map((t: string, i: number) => <span key={i} className="kbd">{t}</span>)}</div>}
                {run.error && <div className="mono" style={{ color: 'var(--st-contradicted)', marginTop: 4 }}>{run.error}</div>}
              </div>
            ))}
          </div>
        )}
        {tab === 'memory' && (
          <div className="stack" style={{ gap: 10 }}>
            <div><div className="label">Scope</div><div style={{ fontSize: 13 }}>{d?.scope_description}</div></div>
            <div><div className="label">Brief</div><div style={{ fontSize: 13 }}>{n.brief || '—'}</div></div>
            <div><div className="label">Memory ({role ? org.topology.roles[n.role] && (d?.role?.memory ?? '') : ''})</div>
              <div className="untrusted" style={{ fontFamily: 'var(--font-ui)', fontSize: 13 }}>{n.notes || 'No notes yet.'}</div></div>
          </div>
        )}
        {tab === 'steer' && (
          <div className="stack" style={{ gap: 14 }}>
            <form className="stack" style={{ gap: 6 }} onSubmit={(e) => { e.preventDefault(); act({ action: 'run', agent_id: n.id, task }); setTask('') }}>
              <span className="label">Re-run with a task</span>
              <textarea className="input" rows={2} value={task} onChange={(e) => setTask(e.target.value)} placeholder="e.g. Compare this division with yesterday; who joined?" />
              <button className="btn" disabled={busy || n.status === 'retired'} style={{ alignSelf: 'flex-start' }}>Run now</button>
            </form>
            {canSpawn.length > 0 && (
              <form className="stack" style={{ gap: 6 }} onSubmit={(e) => { e.preventDefault(); if (spawnRole) act({ action: 'spawn', role: spawnRole, scope: spawnScope, brief, parent: n.id }) }}>
                <span className="label">Spawn a sub-agent</span>
                <div className="row">
                  <select className="input" value={spawnRole} onChange={(e) => setSpawnRole(e.target.value)} style={{ maxWidth: 190 }}>
                    <option value="">role…</option>{canSpawn.map((c) => <option key={c} value={c}>{org.topology.roles[c]?.title ?? c}</option>)}
                  </select>
                  <select className="input" value={spawnScope} onChange={(e) => setSpawnScope(e.target.value)}>
                    <option value={n.scope}>{n.scope === 'population' ? 'whole population' : n.scope_label}</option>
                    {org.divisions.map((dv) => <option key={dv.id} value={`division:${dv.id}`}>{dv.label}</option>)}
                  </select>
                </div>
                <input className="input" value={brief} onChange={(e) => setBrief(e.target.value)} placeholder="Brief: what should it find out?" />
                <button className="btn" disabled={busy || !spawnRole} style={{ alignSelf: 'flex-start' }}>Spawn and run</button>
              </form>
            )}
            {n.id !== org.root && n.status !== 'retired' && (
              <button className="btn danger" style={{ alignSelf: 'flex-start' }} onClick={() => act({ action: 'retire', agent_id: n.id })}>Retire this agent</button>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

function Divisions({ org, reload, onSel }: { org: OrgSnap; reload: () => void; onSel: (id: string) => void }) {
  const [pick, setPick] = useState<Set<string>>(new Set())
  if (!org.divisions.length) return <Empty title="No divisions yet.">They form once the population has enough activity.</Empty>
  const max = Math.max(1, ...org.divisions.map((d) => d.events))
  return (
    <div>
      {pick.size >= 2 && <div className="row" style={{ marginBottom: 8 }}>
        <button className="btn sm" onClick={() => post('/api/agents/action', { action: 'merge', divisions: [...pick] }).then(() => { setPick(new Set()); reload() })}>Merge {pick.size} divisions</button></div>}
      <table className="t">
        <thead><tr><th style={{ width: 22 }} /><th>Division</th><th>Agents</th><th style={{ width: '22%' }}>Recent events</th><th>Covered by</th><th /></tr></thead>
        <tbody>
          {org.divisions.map((d) => {
            const trend = d.events > d.prev_events * 1.3 + 2 ? '↗' : d.events < d.prev_events * 0.7 ? '↘' : '→'
            return (
              <tr key={d.id}>
                <td><input type="checkbox" checked={pick.has(d.id)} onChange={(e) => { const p = new Set(pick); e.target.checked ? p.add(d.id) : p.delete(d.id); setPick(p) }} /></td>
                <td><div style={{ fontWeight: 500 }}>{d.label}</div><div className="mono muted">{d.kind}{d.parent ? ' · from split' : ''} · {d.families.join(', ')}</div></td>
                <td style={{ fontSize: 12.5 }} title={d.agent_labels.join(', ')}>{d.agents.length} <span className="muted">· {d.agent_labels.slice(0, 3).join(', ')}{d.agents.length > 3 ? '…' : ''}</span></td>
                <td><Bar value={d.events} max={max} color="var(--c2)" /><span className="mono muted" style={{ fontSize: 10 }}>{d.events} {trend} (was {d.prev_events})</span></td>
                <td>{d.covered_by.length ? d.covered_by.map((id: string) => <button key={id} className="claim-ref" onClick={() => onSel(id)}>{org.nodes.find((n) => n.id === id)?.role ?? id}</button>)
                  : <span className="chip soft" style={{ color: 'var(--lv-investigate)' }}>blind spot</span>}</td>
                <td><button className="btn ghost sm" onClick={() => post('/api/agents/action', { action: 'split', division: d.id }).then(reload)}>Split</button></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/* ================================================================== topology editor */
function TopologyEditor({ onApplied }: { onApplied: () => void }) {
  const [data, setData] = useState<any>(null)
  const [t, setT] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [saveAs, setSaveAs] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const load = () => get('/api/agents/topologies').then((d) => { setData(d); setT(structuredClone(d.current)); setOpen(d.current?.root ?? null) })
  useEffect(() => { load() }, [])
  if (!data || !t) return null
  const v = data.vocab
  const roles = Object.keys(t.roles)
  const setRole = (rid: string, k: string, val: unknown) => setT({ ...t, roles: { ...t.roles, [rid]: { ...t.roles[rid], [k]: val } } })
  const toggleIn = (rid: string, k: string, item: string) => {
    const cur: string[] = t.roles[rid][k] ?? []
    setRole(rid, k, cur.includes(item) ? cur.filter((x) => x !== item) : [...cur, item])
  }
  const apply = async (save: boolean) => {
    setErr(null); setOk(null)
    try {
      const r = await fetch('/api/agents/topology', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topology: t, save_as: save ? saveAs : undefined }) })
      if (!r.ok) { setErr((await r.json()).detail ?? 'invalid topology'); return }
      setOk(save ? `Saved as ${saveAs} and applied` : 'Applied to the running organization'); onApplied(); load()
    } catch (e) { setErr(String(e)) }
  }
  const addRole = () => {
    let id = 'new_role', i = 1
    while (t.roles[id]) id = `new_role_${i++}`
    setT({ ...t, roles: { ...t.roles, [id]: { title: 'New role', kind: 'analyst', description: '', prompt: '', prompt_text: 'You are …',
      model: 'claude-sonnet-5-5', effort: 'low', max_turns: 8, tools: ['evidence.*'], raw_access: false, can_spawn: [], output: 'division_report',
      memory: 'notes', scope: 'division', refresh_every_cycles: 1, native_subagents: [] } } })
    setOpen(id)
  }
  const removeRole = (rid: string) => {
    const r = { ...t.roles }; delete r[rid]
    for (const k of Object.keys(r)) r[k] = { ...r[k], can_spawn: (r[k].can_spawn ?? []).filter((x: string) => x !== rid) }
    setT({ ...t, roles: r })
  }
  const toolOptions = ['evidence.*', ...v.evidence_tools.map((x: string) => `evidence.${x}`), 'org.*', ...v.org_tools.map((x: string) => `org.${x}`)]
  return (
    <div className="stack" style={{ gap: 16 }}>
      <Panel title="Topology" right={
        <div className="row">
          <select className="input" style={{ width: 260 }} value="" onChange={async (e) => {
            if (!e.target.value) return
            await post('/api/agents/topology', { select: e.target.value }); onApplied(); load()
          }}>
            <option value="">Switch to a saved topology…</option>
            {data.topologies.map((x: any) => <option key={x.id} value={x.id}>{x.title} ({x.id})</option>)}
          </select>
        </div>}>
        <div className="grid" style={{ gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 12 }}>
          <label className="stack" style={{ gap: 4 }}><span className="label">Title</span><input className="input" value={t.title} onChange={(e) => setT({ ...t, title: e.target.value })} /></label>
          <label className="stack" style={{ gap: 4 }}><span className="label">Root role (the main agent)</span>
            <select className="input" value={t.root} onChange={(e) => setT({ ...t, root: e.target.value })}>{roles.map((r) => <option key={r}>{r}</option>)}</select></label>
          <div className="stack" style={{ gap: 4 }}><span className="label">Cycle phases</span>
            <div className="row" style={{ gap: 10 }}>{['refresh_children', 'root', 'maintain'].map((p) => (
              <label key={p} className="row mono" style={{ gap: 5 }}><input type="checkbox" checked={t.cycle.includes(p)}
                onChange={() => setT({ ...t, cycle: ['refresh_children', 'root', 'maintain'].filter((x) => x === p ? !t.cycle.includes(p) : t.cycle.includes(x)) })} />{p.replace('_', ' ')}</label>))}</div></div>
          <label className="stack" style={{ gap: 4, gridColumn: 'span 3' }}><span className="label">Description</span>
            <input className="input" value={t.description} onChange={(e) => setT({ ...t, description: e.target.value })} /></label>
        </div>
      </Panel>

      <div className="grid">
        <Panel title="Scaling" className="span-4">
          <NumGrid obj={t.scaling} keys={['max_agents', 'max_depth', 'max_concurrent_runs', 'budget_usd_per_cycle', 'budget_usd_total', 'stale_after_windows']} onChange={(o) => setT({ ...t, scaling: o })} />
        </Panel>
        <Panel title="Divisions" className="span-4">
          <label className="stack" style={{ gap: 4, marginBottom: 8 }}><span className="label">Strategy</span>
            <select className="input" value={t.divisions.strategy} onChange={(e) => setT({ ...t, divisions: { ...t.divisions, strategy: e.target.value } })}>
              {v.division_strategies.map((s: string) => <option key={s}>{s}</option>)}</select></label>
          <NumGrid obj={t.divisions} keys={['max', 'min_events', 'lookback_windows', 'grace_refreshes']} onChange={(o) => setT({ ...t, divisions: o })} />
        </Panel>
        <Panel title="Maintenance policy" className="span-4">
          <label className="stack" style={{ gap: 4, marginBottom: 8 }}><span className="label">Cover every division with</span>
            <select className="input" value={t.maintain.cover_divisions_with ?? ''} onChange={(e) => setT({ ...t, maintain: { ...t.maintain, cover_divisions_with: e.target.value || null } })}>
              <option value="">nobody (the main agent decides)</option>{roles.map((r) => <option key={r}>{r}</option>)}</select></label>
          <NumGrid obj={t.maintain} keys={['retire_quiet_cycles', 'split_when_events_over']} onChange={(o) => setT({ ...t, maintain: o })} />
        </Panel>
      </div>

      <div className="row"><span className="h-section">Roles</span><span className="muted" style={{ fontSize: 13 }}>Each role is a kind of agent: what it reads, what it may spawn, what it must return.</span>
        <button className="btn sm" style={{ marginLeft: 'auto' }} onClick={addRole}><Icon name="plus" size={13} />Add role</button></div>
      {roles.map((rid) => {
        const r = t.roles[rid]
        const isOpen = open === rid
        return (
          <section key={rid} className="panel" style={{ borderLeft: `3px solid ${roleColor(roles, rid)}` }}>
            <button className="panel-head" style={{ background: 'none', border: 0, width: '100%', cursor: 'pointer', textAlign: 'left' }} onClick={() => setOpen(isOpen ? null : rid)}>
              <span className="title">{r.title}</span><span className="mono muted">{rid}{rid === t.root ? ' · root' : ''}</span>
              <span className="mono muted" style={{ marginLeft: 'auto' }}>{r.model} · {r.effort} · {r.output} · spawns {(r.can_spawn ?? []).join(', ') || 'nothing'}</span>
            </button>
            {isOpen && (
              <div className="panel-body stack" style={{ gap: 12 }}>
                <div className="grid" style={{ gridTemplateColumns: 'repeat(4, minmax(0,1fr))', gap: 10 }}>
                  <Field l="Title"><input className="input" value={r.title} onChange={(e) => setRole(rid, 'title', e.target.value)} /></Field>
                  <Field l="Deterministic behaviour"><select className="input" value={r.kind} onChange={(e) => setRole(rid, 'kind', e.target.value)}>{v.kinds.map((k: string) => <option key={k}>{k}</option>)}</select></Field>
                  <Field l="Model"><select className="input" value={r.model} onChange={(e) => setRole(rid, 'model', e.target.value)}>{v.models.map((k: string) => <option key={k}>{k}</option>)}</select></Field>
                  <Field l="Effort"><select className="input" value={r.effort} onChange={(e) => setRole(rid, 'effort', e.target.value)}>{v.efforts.map((k: string) => <option key={k}>{k}</option>)}</select></Field>
                  <Field l="Max turns"><input className="input" type="number" value={r.max_turns} onChange={(e) => setRole(rid, 'max_turns', +e.target.value)} /></Field>
                  <Field l="Scope"><select className="input" value={r.scope} onChange={(e) => setRole(rid, 'scope', e.target.value)}>{v.scopes.map((k: string) => <option key={k}>{k}</option>)}</select></Field>
                  <Field l="Output schema"><select className="input" value={r.output} onChange={(e) => setRole(rid, 'output', e.target.value)}>{v.schemas.map((k: string) => <option key={k}>{k}</option>)}</select></Field>
                  <Field l="Memory"><select className="input" value={r.memory} onChange={(e) => setRole(rid, 'memory', e.target.value)}>{v.memory.map((k: string) => <option key={k}>{k}</option>)}</select></Field>
                  <Field l="Refresh every N cycles (0 = on demand)"><input className="input" type="number" value={r.refresh_every_cycles} onChange={(e) => setRole(rid, 'refresh_every_cycles', +e.target.value)} /></Field>
                  <Field l="Backend override"><select className="input" value={r.backend ?? ''} onChange={(e) => setRole(rid, 'backend', e.target.value || null)}>
                    <option value="">follow LLM mode</option>{v.backends.map((k: string) => <option key={k}>{k}</option>)}</select></Field>
                  <Field l="Raw text access"><Toggle on={!!r.raw_access} onChange={(x) => setRole(rid, 'raw_access', x)} /></Field>
                  <Field l="Description"><input className="input" value={r.description} onChange={(e) => setRole(rid, 'description', e.target.value)} /></Field>
                </div>
                <Chips label="Tools" all={toolOptions} on={r.tools ?? []} onToggle={(x) => toggleIn(rid, 'tools', x)} />
                <Chips label="May spawn" all={roles.filter((x) => x !== rid)} on={r.can_spawn ?? []} onToggle={(x) => toggleIn(rid, 'can_spawn', x)} />
                {Object.keys(t.helpers ?? {}).length > 0 && <Chips label="Native Claude Code subagents (Task tool)" all={Object.keys(t.helpers)} on={r.native_subagents ?? []} onToggle={(x) => toggleIn(rid, 'native_subagents', x)} />}
                {r.output === 'custom' && <Field l="Custom output JSON schema">
                  <textarea className="input mono" rows={6} defaultValue={JSON.stringify(r.output_schema ?? { type: 'object', properties: {} }, null, 2)}
                    onBlur={(e) => { try { setRole(rid, 'output_schema', JSON.parse(e.target.value)) } catch { setErr('custom schema is not valid JSON') } }} /></Field>}
                <Field l={`Prompt${r.prompt?.endsWith?.('.md') ? ` (from ${r.prompt}; edits are saved inline)` : ''}`}>
                  <textarea className="input" rows={8} style={{ fontFamily: 'var(--font-ui)', fontSize: 13 }} value={r.prompt_text ?? r.prompt ?? ''} onChange={(e) => setRole(rid, 'prompt_text', e.target.value)} /></Field>
                {rid !== t.root && <button className="btn danger sm" style={{ alignSelf: 'flex-start' }} onClick={() => removeRole(rid)}>Remove role</button>}
              </div>
            )}
          </section>
        )
      })}

      <section className="panel" style={{ position: 'sticky', bottom: 12, zIndex: 4, boxShadow: 'var(--shadow-2)' }}>
        <div className="panel-body row" style={{ padding: 14, gap: 10, flexWrap: 'wrap' }}>
          {err && <span className="mono" style={{ color: 'var(--st-contradicted)', flex: '1 1 100%' }}>{err}</span>}
          {ok && <span className="chip soft st-OBSERVED"><span className="dot" />{ok}</span>}
          <button className="btn ghost" onClick={load}>Discard changes</button>
          <span style={{ marginLeft: 'auto' }} />
          <input className="input" style={{ width: 200 }} placeholder="save as (id)" value={saveAs} onChange={(e) => setSaveAs(e.target.value)} />
          <button className="btn" disabled={!saveAs} onClick={() => apply(true)}>Save as file & apply</button>
          <button className="btn accent" onClick={() => apply(false)}>Apply to running organization</button>
        </div>
      </section>
    </div>
  )
}

function Field({ l, children }: { l: string; children: React.ReactNode }) {
  return <label className="stack" style={{ gap: 4 }}><span className="label">{l}</span>{children}</label>
}
function Chips({ label, all, on, onToggle }: { label: string; all: string[]; on: string[]; onToggle: (x: string) => void }) {
  return (
    <div><div className="label" style={{ marginBottom: 5 }}>{label}</div>
      <div className="row" style={{ gap: 5, flexWrap: 'wrap' }}>
        {all.map((x) => <button key={x} type="button" className={`btn sm ${on.includes(x) ? 'primary' : ''}`} onClick={() => onToggle(x)}>{x}</button>)}
      </div></div>
  )
}
function NumGrid({ obj, keys, onChange }: { obj: any; keys: string[]; onChange: (o: any) => void }) {
  return (
    <div className="grid" style={{ gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 8 }}>
      {keys.map((k) => (
        <label key={k} className="stack" style={{ gap: 3 }}><span className="label">{k.replace(/_/g, ' ')}</span>
          <input className="input" type="number" step="any" value={obj[k] ?? ''} placeholder="off"
            onChange={(e) => onChange({ ...obj, [k]: e.target.value === '' ? null : +e.target.value })} /></label>
      ))}
    </div>
  )
}

/* ================================================================== situation-room panel */
export function OrgMini({ s }: { s: Snapshot }) {
  const setRoute = useStore((x) => x.setRoute)
  const a = (s as any).agents
  if (!a) return null
  const roles = Object.keys(a.by_role)
  const byId = Object.fromEntries(a.tree.map((n: any) => [n.id, n]))
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row" style={{ gap: 12 }}>
        <span><span className="display" style={{ fontSize: 26 }}>{a.agents}</span> <span className="muted">agents over {a.divisions} divisions</span></span>
        <span className="mono muted" style={{ marginLeft: 'auto' }}>cycle {a.cycle}{a.spent ? ` · $${a.spent.toFixed(2)}` : ''}</span>
      </div>
      <div style={{ maxHeight: 300, overflow: 'auto' }}>
        {a.tree.slice(0, 14).map((n: any) => (
          <div key={n.id} className="row" style={{ gap: 7, padding: '3px 0', paddingLeft: Math.min(3, depthOf(n, byId)) * 16 }}>
            <span className={`live-dot ${n.status === 'running' ? 'run' : ''}`} style={{ background: roleColor(roles, n.role), boxShadow: n.status === 'running' ? undefined : 'none', width: 7, height: 7 }} />
            <span style={{ fontSize: 12.5, fontWeight: 500, whiteSpace: 'nowrap' }}>{n.title.split(' · ').slice(-1)[0]}</span>
            <span className="muted" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{n.headline}</span>
          </div>
        ))}
      </div>
      <button className="btn" style={{ alignSelf: 'flex-start' }} onClick={() => setRoute('organization' as any)}>Open organization <Icon name="arrow" size={13} /></button>
    </div>
  )
}
function depthOf(n: any, byId: Record<string, any>): number {
  let d = 0, cur = n
  while (cur?.parent && byId[cur.parent] && d < 5) { d++; cur = byId[cur.parent] }
  return d
}
