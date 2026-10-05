import React, { useState } from 'react'
import { post } from '../api'
import { Empty, Icon, Panel, pct } from '../components/ui'

const ORGS = [
  { id: 'default', label: 'Adaptive hierarchy' },
  { id: 'baseline_deterministic', label: 'Deterministic only' },
  { id: 'baseline_uniform_local', label: 'Uniform local summarizers' },
  { id: 'baseline_single_summarizer', label: 'Single global summarizer' },
]

export function Evaluate() {
  const [sel, setSel] = useState<string[]>(ORGS.map((o) => o.id))
  const [res, setRes] = useState<any | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true)
    try { setRes(await post('/api/eval', { orgs: sel })) } finally { setBusy(false) }
  }
  const rows = res?.results ?? []
  return (
    <div className="fade-in">
      <div className="page-title">Evaluate monitoring strategies</div>
      <div className="muted" style={{ marginBottom: 18, maxWidth: 780 }}>
        SwarmFrame is a test bed: each baseline is just another organization config. Runs replay the synthetic AI Village corpus,
        which has planted ground truth (convergence, propagation with and without exposure, a false completion report, an operator
        burst, a surge, a drift), and score how each organization finds and explains it.
      </div>
      <Panel title="Organizations to compare" right={<button className="btn accent" disabled={busy || !sel.length} onClick={run}>
        <Icon name={busy ? 'spark' : 'play'} size={14} />{busy ? 'Running…' : 'Run comparison'}</button>}>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          {ORGS.map((o) => (
            <label key={o.id} className="card row" style={{ cursor: 'pointer', gap: 8, padding: '8px 12px' }}>
              <input type="checkbox" checked={sel.includes(o.id)} onChange={(e) => setSel(e.target.checked ? [...sel, o.id] : sel.filter((x) => x !== o.id))} />
              {o.label}
            </label>
          ))}
        </div>
      </Panel>
      <div style={{ height: 16 }} />
      {!rows.length ? <Panel title="Results"><Empty title="No runs yet.">Deterministic mode makes runs free; switch the LLM mode in Configure to compare model-based strategies.</Empty></Panel> : (
        <>
          <Panel title="Results" kicker={`${res.source} · ${res.path}`}>
            <table className="t">
              <thead><tr><th>Organization</th><th className="num">Recall</th><th className="num">Explained</th><th className="num">Min to signal</th>
                <th className="num">Min to explanation</th><th>Exposure correct</th><th className="num">False incidents</th><th className="num">Unsupported inf.</th>
                <th className="num">LLM calls</th><th className="num">Coverage</th><th className="num">Secs</th></tr></thead>
              <tbody>
                {rows.map((r: any) => r.error ? <tr key={r.org}><td>{r.org}</td><td colSpan={10} style={{ color: 'var(--st-contradicted)' }}>{r.error}</td></tr> : (
                  <tr key={r.org}>
                    <td><div style={{ fontWeight: 600 }}>{r.name}</div><div className="mono muted">{r.org} · {r.llm_mode}</div></td>
                    <td className="num">{pct(r.recall)}</td><td className="num">{pct(r.explained)}</td>
                    <td className="num">{r.median_minutes_to_signal ?? '—'}</td><td className="num">{r.median_minutes_to_explanation ?? '—'}</td>
                    <td className="mono">{r.exposure_correct == null ? '—' : r.exposure_correct ? 'yes' : 'no'}</td>
                    <td className="num">{r.false_incidents}</td><td className="num">{pct(r.unsupported_inference_rate)}</td>
                    <td className="num">{r.llm_calls}</td><td className="num">{pct(r.coverage)}</td><td className="num">{r.seconds}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <div style={{ height: 16 }} />
          <Panel title="Per incident">
            <table className="t">
              <thead><tr><th>Incident</th>{rows.filter((r: any) => !r.error).map((r: any) => <th key={r.org}>{r.name}</th>)}</tr></thead>
              <tbody>
                {(rows.find((r: any) => !r.error)?.incidents_detail ?? []).map((inc: any, i: number) => (
                  <tr key={inc.incident}>
                    <td><div style={{ fontWeight: 500 }}>{inc.kind}</div><div className="mono muted">{inc.incident}</div></td>
                    {rows.filter((r: any) => !r.error).map((r: any) => {
                      const d = r.incidents_detail[i]
                      return <td key={r.org} style={{ fontSize: 12.5 }}>
                        <span className="mono" style={{ color: d.detected ? 'var(--st-observed)' : 'var(--st-contradicted)' }}>{d.detected ? `found +${d.minutes_to_signal}m` : 'missed'}</span>
                        {d.explained && <div className="italic" style={{ fontSize: 13.5, color: 'var(--ink-2)' }}>{d.conclusion?.slice(0, 120)}</div>}
                      </td>
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}
    </div>
  )
}
