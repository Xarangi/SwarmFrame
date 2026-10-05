import React from 'react'
import { useStore } from '../store'
import type { Snapshot, TriageItem } from '../types'
import { Empty, fmtNum, pct } from '../components/ui'
import { Sparkline } from '../primitives/charts'

const LANE_COLOR: Record<string, string> = { triage: 'var(--accent)', coverage: 'var(--c2)', audit: 'var(--c4)' }
const LANE_NAME: Record<string, string> = { triage: 'priority', coverage: 'unread longest', audit: 'spot-check' }
const LANE_TEXT: Record<string, string> = {
  triage: 'scored highest: severity, change, novelty, time since a look', coverage: 'nobody has read it for the longest time',
  audit: 'picked at random, so the scoring cannot hide anything',
}

export function LaneChip({ lane }: { lane: string }) {
  return <span className="chip soft" title={LANE_TEXT[lane]} style={{ color: LANE_COLOR[lane] ?? 'var(--ink-3)' }}><span className="dot" />{LANE_NAME[lane] ?? lane}</span>
}

function changeColor(c: string) {
  const n = parseFloat(c)
  return Math.abs(n) < 25 ? 'var(--ink-3)' : n > 0 ? 'var(--accent)' : 'var(--c2)'
}

export function CohortsPanel({ s }: { s: Snapshot }) {
  const sc = s.scale
  const open = useStore((x) => x.openDrawer)
  if (!sc || !sc.cohorts.length) return <Empty title="No groups yet.">Groups form as activity arrives.</Empty>
  const pop = sc.population
  return (
    <div>
      <div className="row mono muted" style={{ gap: 14, marginBottom: 10, flexWrap: 'wrap' }}>
        <span>{fmtNum(pop.units_active)} {pop.unit === 'actor' ? s.source.noun + 's' : 'targets'} active</span>
        <span>{pop.cohorts} groups</span>
        <span title="members that behave unlike the rest of their group">{pop.outliers} stand out</span>
        <span>largest group {pop.largest_cohort}</span>
      </div>
      <div className="stack" style={{ gap: 0, maxHeight: 440, overflow: 'auto', marginRight: -8, paddingRight: 8 }}>
        {sc.cohorts.slice(0, 12).map((c) => (
          <div key={c.id} className="list-item">
            <div className="row" style={{ alignItems: 'baseline' }}>
              <span style={{ fontWeight: 500, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.id}>{c.label}</span>
              {c.new && <span className="chip soft" style={{ color: 'var(--accent)' }}>new</span>}
              <span className="mono muted">{c.units} {pop.unit === 'actor' ? s.source.noun + 's' : 'targets'}</span>
              <span className="mono" style={{ color: changeColor(c.change), minWidth: 52, textAlign: 'right' }}>{c.change}</span>
            </div>
            <div className="row mono muted" style={{ gap: 10, marginTop: 3, fontSize: 11 }}>
              <span>{c.events_prev}→{c.events_now} events</span>
              {c.top_resources[0] && <span>on {c.top_resources.slice(0, 2).map((r) => r.label).join(', ')}</span>}
            </div>
            {c.outliers.length > 0 && (
              <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 5 }}>
                {c.outliers.slice(0, 3).map((o) => (
                  <button key={o.unit} className="chip soft" style={{ color: 'var(--st-self)', cursor: 'pointer', textTransform: 'none', letterSpacing: 0 }}
                    title={`${o.why} (${Math.round(o.score * 100)}% unlike its group)`} onClick={() => open({ kind: 'entity', id: o.unit })}>
                    <span className="dot" />{o.label} · {o.why}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function agentTitle(s: Snapshot, id: string | null): string {
  if (!id) return 'unassigned'
  const n = (s as any).agents?.tree?.find((t: any) => t.id === id)
  return n ? n.title.split(' · ')[0] : id
}

export function TriagePanel({ s }: { s: Snapshot }) {
  const t = s.scale?.triage
  if (!t || !t.items.length) return <Empty title="No reading plan yet.">The analysts plan their reading at each cycle.</Empty>
  const lanes = ['triage', 'coverage', 'audit']
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 12 }}>
        {lanes.map((l) => {
          const hr = t.hit_rates[l]
          const n = t.items.filter((i) => i.lane === l).length
          return (
            <div key={l} className="card" style={{ padding: '8px 10px' }}>
              <div className="row" style={{ justifyContent: 'space-between' }}><LaneChip lane={l} /><span className="mono" title="picks in this lane / reads this cycle">{n} of {t.reads_per_cycle}</span></div>
              <div className="muted" style={{ fontSize: 11.5, marginTop: 4, lineHeight: 1.35 }}>{LANE_TEXT[l]}</div>
              <div className="row mono" style={{ marginTop: 6, gap: 6 }}>
                <span className="muted">found something</span><span style={{ marginLeft: 'auto' }}>{hr == null ? '–' : pct(hr)}</span>
              </div>
            </div>
          )
        })}
      </div>
      {t.warnings.map((w) => <div key={w} className="card" style={{ borderColor: 'var(--accent)', marginBottom: 8, fontSize: 13 }}>{w}</div>)}
      <div className="stack" style={{ gap: 0, maxHeight: 360, overflow: 'auto', marginRight: -8, paddingRight: 8 }}>
        {t.items.map((i: TriageItem) => (
          <div key={i.scope + i.lane} className="list-item">
            <div className="row" style={{ alignItems: 'baseline' }}>
              <LaneChip lane={i.lane} />
              <span style={{ fontWeight: 500, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{i.label}</span>
              <span className="mono muted">{i.kind === 'cohort' ? 'group' : i.kind}{i.n_units > 1 ? ` · ${i.n_units}` : ''}</span>
              {i.lane !== 'audit' && <span className="mono" title="priority score, 0 to 1" style={{ minWidth: 34, textAlign: 'right' }}>{Math.round(i.priority * 100)}</span>}
            </div>
            <div className="mono muted" style={{ fontSize: 11, marginTop: 3 }}>{i.reasons.slice(0, 3).join(' · ')}</div>
            <div className="mono" style={{ fontSize: 10.5, marginTop: 2, color: i.assigned_to ? 'var(--ink-3)' : 'var(--st-contradicted)' }}>{i.assigned_to ? `read by ${agentTitle(s, i.assigned_to)}` : 'nobody free to read it'}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function CoveragePanel({ s }: { s: Snapshot }) {
  const c = s.scale?.coverage
  const hist = s.scale?.coverage_history ?? []
  if (!c) return <Empty title="Nothing read yet.">Written at the end of each analyst cycle.</Empty>
  const share = c.share_of_activity_looked_at_now
  return (
    <div>
      <div className="row" style={{ alignItems: 'flex-end', gap: 14 }}>
        <div>
          <div className="display" style={{ fontSize: 40, lineHeight: 1 }}>{share == null ? '–' : pct(share)}</div>
          <div className="label" style={{ marginTop: 4 }}>of recent activity got a close look</div>
        </div>
        <div style={{ marginLeft: 'auto' }}>
          <Sparkline values={hist.map((h) => h.share_of_activity_looked_at_now ?? 0)} width={130} height={34} />
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 14px', marginTop: 12 }} className="mono">
        <span className="muted">events this cycle</span><span style={{ textAlign: 'right' }}>{fmtNum(c.events_in_span)}</span>
        <span className="muted">messages, by type</span><span style={{ textAlign: 'right' }}>{fmtNum(c.messages)} in {c.templates} types</span>
        <span className="muted">groups read this cycle</span><span style={{ textAlign: 'right' }}>{c.cohorts_looked_at_now} of {c.cohorts}</span>
        <span className="muted">… in recent cycles</span><span style={{ textAlign: 'right' }}>{c.cohorts_looked_at_recently}</span>
        <span className="muted">random spot-checks</span><span style={{ textAlign: 'right' }}>{c.random_audits_now}</span>
        <span className="muted">messages read word for word</span><span style={{ textAlign: 'right' }}>{c.raw_reads_now}</span>
        <span className="muted">analyst runs</span><span style={{ textAlign: 'right' }}>{c.agent_runs_now}</span>
      </div>
      {(c.stale_cohorts_total > 0 || c.unassigned_picks.length > 0) && (
        <div style={{ marginTop: 12 }}>
          <div className="label">Not read yet</div>
          {c.stale_cohorts.slice(0, 4).map((x) => <div key={x.id} className="row mono" style={{ fontSize: 11.5, marginTop: 3 }}><span style={{ flex: 1 }}>{x.label}</span><span className="muted">{x.events_now} ev</span></div>)}
          {c.stale_cohorts_total > 4 && <div className="mono muted" style={{ fontSize: 11 }}>+{c.stale_cohorts_total - 4} more groups not read lately</div>}
          {c.unassigned_picks.length > 0 && <div className="mono" style={{ fontSize: 11.5, marginTop: 4, color: 'var(--st-contradicted)' }}>{c.unassigned_picks.length} picks had nobody free to read them</div>}
        </div>
      )}
    </div>
  )
}

export function TemplatesPanel({ s }: { s: Snapshot }) {
  const t = s.scale?.templates ?? []
  const pop = s.scale?.population
  if (!t.length) return <Empty title="No message types yet." />
  return (
    <div>
      {pop && <div className="muted" style={{ marginBottom: 8, fontSize: 12.5 }}>{fmtNum(pop.messages)} messages come in {pop.templates} shapes. The wording is agent text and stays hidden; how far each shape spread is what matters.</div>}
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead><tr>{['type', 'messages', 'senders', 'groups', 'recent'].map((h) => <th key={h} className="label" style={{ textAlign: h === 'type' ? 'left' : 'right', paddingBottom: 6, borderBottom: '1px solid var(--line)' }}>{h}</th>)}</tr></thead>
        <tbody>
          {t.slice(0, 10).map((r) => (
            <tr key={r.id}>
              <td className="mono" style={{ padding: '5px 0', borderBottom: '1px solid var(--line-2)' }}>{r.id}{r.new && <span className="chip soft" style={{ color: 'var(--accent)', marginLeft: 6 }}>new</span>}</td>
              <td className="mono" style={{ textAlign: 'right', borderBottom: '1px solid var(--line-2)' }}>{fmtNum(r.messages)}</td>
              <td className="mono" style={{ textAlign: 'right', borderBottom: '1px solid var(--line-2)' }}>{r.units}</td>
              <td className="mono" style={{ textAlign: 'right', borderBottom: '1px solid var(--line-2)' }}>{r.cohorts}</td>
              <td className="mono" style={{ textAlign: 'right', borderBottom: '1px solid var(--line-2)', color: r.now > 2 * r.prev && r.now > 4 ? 'var(--accent)' : undefined }}>{r.prev}→{r.now}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
