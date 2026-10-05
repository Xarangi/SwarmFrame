import React, { useState } from 'react'
import { api } from '../api'
import type { Snapshot } from '../types'
import { Bar, Empty, fmtNum, fmtTime, Icon, Panel, ScopeLink } from '../components/ui'

/** Supervise the supervisor: where the monitoring system spends cognition, and the top-down directives that steer it. */
export function MonitorAttention({ s }: { s: Snapshot }) {
  const [scope, setScope] = useState('')
  const [weight, setWeight] = useState(1.5)
  const rows = s.attention.by_scope
  const max = Math.max(1, ...rows.map((r) => r.tokens || r.calls))
  const roles = Object.entries(s.attention.by_role).sort((a, b) => b[1] - a[1])
  const roleMax = Math.max(1, ...roles.map((r) => r[1]))
  const dirs = [...s.directives].reverse()
  return (
    <div className="fade-in">
      <header className="page-head"><div>
        <h1 className="page-title">Where monitoring effort goes</h1>
        <p className="page-sub">Monitors report what they see; SwarmFrame steers where they look. This page shows both, so you can
          check the monitoring itself and override it.</p>
      </div></header>
      <div className="grid">
        <Panel title="Effort by scope" className="span-7" kicker={s.health.llm_mode === 'stub' ? 'estimated · models off' : 'from model usage'}>
          {!rows.length ? <Empty title="No effort spent yet." /> : (
            <table className="t">
              <thead><tr><th>Scope</th><th>Monitors</th><th className="num">Investigators</th><th className="num">Calls</th><th style={{ width: '24%' }}>Effort</th><th className="num">Focus</th><th /></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.scope}>
                    <td><ScopeLink scope={r.scope} label={r.label} /></td>
                    <td className="mono muted">{r.monitors.join(', ') || '—'}</td>
                    <td className="num">{r.investigators}</td>
                    <td className="num">{r.calls}</td>
                    <td><Bar value={r.tokens || r.calls} max={max} color={r.focus ? 'var(--accent)' : 'var(--ink-4)'} />
                      <span className="mono muted" style={{ fontSize: 10 }}>{fmtNum(r.tokens)} tok · ${r.cost_usd.toFixed(3)}</span></td>
                    <td className="num">{r.focus ? r.focus.toFixed(1) : '—'}</td>
                    <td>
                      {r.focus ? <button className="btn ghost sm" onClick={() => api.directive('defocus', r.scope)}>Defocus</button>
                        : <button className="btn ghost sm" onClick={() => api.directive('focus', r.scope, { weight: 1.5 })}>Focus</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <div className="span-5 stack" style={{ gap: 16 }}>
          <Panel title="Where to look harder" kicker={`${s.attention_policy.length} focused`}>
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>A focused scope gets denser retrieval and lower escalation thresholds. Yours take precedence over SwarmFrame’s.</div>
            {s.attention_policy.map((f) => (
              <div key={f.scope} className="list-item row">
                <span className="chip soft" style={{ color: f.set_by === 'human' ? 'var(--st-derived)' : 'var(--accent)' }}>{f.set_by}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div><ScopeLink scope={f.scope} /></div>
                  <div className="muted" style={{ fontSize: 12 }}>{f.reason}</div>
                </div>
                <span className="mono">{f.weight.toFixed(1)}</span>
                <button className="btn ghost sm" onClick={() => api.directive('defocus', f.scope)}><Icon name="x" size={12} /></button>
              </div>
            ))}
            <form className="row" style={{ marginTop: 10 }} onSubmit={(e) => { e.preventDefault(); if (scope) { api.directive('focus', scope, { weight }); setScope('') } }}>
              <input className="input" placeholder="scope, e.g. resource:dom:docs.google.com" value={scope} onChange={(e) => setScope(e.target.value)} />
              <input type="range" min={0.5} max={3} step={0.5} value={weight} onChange={(e) => setWeight(+e.target.value)} style={{ width: 80 }} />
              <span className="mono">{weight}</span>
              <button className="btn" type="submit">Focus</button>
            </form>
          </Panel>
          <Panel title="Effort by analyst role">
            {roles.map(([k, v]) => (
              <div key={k} style={{ marginBottom: 8 }}>
                <div className="row" style={{ justifyContent: 'space-between' }}><span>{k}</span><span className="mono muted">{fmtNum(v)} tok</span></div>
                <Bar value={v} max={roleMax} color="var(--c2)" />
              </div>
            ))}
            {!roles.length && <Empty title="Nothing yet." />}
          </Panel>
        </div>
        <Panel title="Suggestions and instructions" className="span-12" kicker={`autonomy: ${s.org.autonomy.replace('_', ' ')}`}>
          {!dirs.length ? <Empty title="Nothing yet.">SwarmFrame suggests these when it wants to look elsewhere or ask a question.</Empty> : (
            <table className="t">
              <thead><tr><th>Time</th><th>Kind</th><th>Scope</th><th>Reason</th><th>From</th><th>Status</th><th /></tr></thead>
              <tbody>
                {dirs.slice(0, 30).map((d) => (
                  <tr key={d.id}>
                    <td className="mono muted">{fmtTime(d.ts, true)}</td>
                    <td><span className="chip soft" style={{ color: 'var(--accent)' }}>{d.kind}</span></td>
                    <td><ScopeLink scope={d.scope} /></td>
                    <td style={{ fontSize: 13 }}>{d.reason}</td>
                    <td className="mono muted">{d.set_by}{d.executive_version ? ` v${d.executive_version}` : ''}</td>
                    <td className="mono" style={{ color: d.status === 'applied' ? 'var(--st-observed)' : d.status === 'rejected' ? 'var(--st-contradicted)' : 'var(--st-inferred)' }}>{d.status}</td>
                    <td>{d.status === 'proposed' && <span className="row" style={{ gap: 4 }}>
                      <button className="btn sm" onClick={() => api.approve(d.id, true)}>Apply</button>
                      <button className="btn ghost sm" onClick={() => api.approve(d.id, false)}>Reject</button></span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </div>
  )
}
