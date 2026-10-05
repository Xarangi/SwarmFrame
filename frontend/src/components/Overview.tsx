import React from 'react'
import { useStore } from '../store'
import type { Cite } from '../types'
import { CiteMarks } from './findings'
import { famColor } from './ui'

/** What's going on: every group's current work and what is emerging, whatever the severity (dashboard/overview.py). */
export interface OverviewGroup {
  group: string; active: number; members: number; events: number; work: number; doing: string
  families: [string, number][]; messages: number; where: string | null; goal: string | null
  trend: 'new' | 'rising' | 'steady' | 'falling' | 'quiet'; shifted_from: string | null; cites: Cite[]
}
export interface OverviewData {
  span: string; group_noun: string; group_plural: string; groups: OverviewGroup[]
  emerging: { kind: string; text: string; cites: Cite[] }[]; summary: string; by_identity: boolean
}

const TREND: Record<string, string> = { new: 'new', rising: 'rising', steady: '', falling: 'slowing', quiet: 'quiet' }
const EMERGE: Record<string, string> = { new_place: 'new place', new_work: 'new work', rising: 'rising', shift: 'shifted', group_active: 'woke up' }

export function Overview({ o }: { o: OverviewData }) {
  const t = useStore((s) => s.snap?.brief?.terms)
  if (!o.groups.length && !o.emerging.length) return null
  const max = Math.max(1, ...o.groups.map((g) => g.work + g.messages))
  return (
    <section className="block overview">
      <div className="block-head">
        <h2 className="h-section">What's going on</h2>
        <span className="muted mono" style={{ fontSize: 11 }}>last {o.span} · whatever the severity</span>
      </div>
      <p className="ov-summary">{o.summary}</p>
      <div className="ov-grid">
        {o.groups.length > 0 && (
          <div className="ov-groups" role="table" aria-label={`What each ${o.group_noun} is doing`}>
            {o.groups.map((g) => (
              <div key={g.group} className={`ov-row trend-${g.trend}`} role="row">
                <div className="ov-name"><b>{g.group}</b><span className="mono muted">{g.active}/{g.members} {t?.agent ?? 'agent'}s</span></div>
                <div className="ov-bar" title={g.families.map(([f, k]) => `${f} ${k}`).join(' · ')}>
                  {g.families.map(([f, k]) => <i key={f} style={{ width: `${(k / max) * 100}%`, background: famColor(f) }} />)}
                </div>
                <div className="ov-what">
                  <span>{g.active ? <>mostly <b>{g.doing}</b>{g.where ? <> on {g.where}</> : null}</> : <span className="muted">quiet</span>}</span>
                  {g.goal && <span className="ov-goal" title="The most common goal these agents stated themselves (agent-written, untrusted)">goal: {g.goal}</span>}
                </div>
                <div className="ov-meta">
                  {TREND[g.trend] && <span className={`ov-trend t-${g.trend}`}>{TREND[g.trend]}</span>}
                  <CiteMarks cites={g.cites} max={2} />
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="ov-emerging">
          <div className="label" style={{ marginBottom: 6 }}>Emerging</div>
          {o.emerging.length ? o.emerging.map((x, i) => (
            <div key={i} className="ov-em">
              <span className={`ov-tag k-${x.kind}`}>{EMERGE[x.kind] ?? x.kind}</span>
              <span>{x.text} <CiteMarks cites={x.cites} max={2} /></span>
            </div>
          )) : <div className="muted" style={{ fontSize: 13 }}>Nothing new in the last {o.span}: the same groups on the same work.</div>}
        </div>
      </div>
    </section>
  )
}
