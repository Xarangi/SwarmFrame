import React, { useMemo, useState } from 'react'
import { api } from '../api'
import type { FindingRow, Severity, Snapshot } from '../types'
import { Empty, Icon, ScopeLink } from '../components/ui'
import { FindingList, SEV_ORDER } from '../components/findings'
import { Term } from '../components/kit'
import { SEVERITY } from '../words'

/** Every open finding, grouped and ranked, plus what SwarmFrame suggests changing about where it looks. */
export function Attention({ s }: { s: Snapshot }) {
  const b = s.brief
  const [sev, setSev] = useState<Severity | 'all'>('all')
  const [q, setQ] = useState('')
  const [flat, setFlat] = useState(false)
  const items = useMemo(() => {
    const src: FindingRow[] = b?.items ?? []
    const rows = flat ? src.flatMap((x) => (x.group && x.member_rows ? x.member_rows.map((m) => ({ ...m, group: false, count: 1, members: [m.id] })) : [x])) : src
    return rows.filter((x) => (sev === 'all' || x.severity === sev) && (!q || (x.headline + x.label).toLowerCase().includes(q.toLowerCase())))
  }, [b, sev, q, flat])
  const proposed = s.directives.filter((d) => d.status === 'proposed')
  if (!b) return <div className="skeleton" style={{ height: 300 }} />
  const total = SEV_ORDER.reduce((n, k) => n + b.counts[k], 0)
  return (
    <div className="fade-in narrow">
      <header className="page-head">
        <div>
          <h1 className="page-title">Attention</h1>
          <p className="page-sub">Every open finding, ranked: <b>act</b> needs a decision, <b>look</b> is worth opening, <b>watch</b> needs nothing yet.
            Similar findings are grouped; open one to see its members, evidence and the investigation.</p>
        </div>
      </header>

      {proposed.length > 0 && (
        <section className="block suggest">
          <div className="block-head"><h2 className="h-section">SwarmFrame suggests</h2><span className="muted"><Term k="directive">changes to where it looks</Term>, waiting for you</span></div>
          {proposed.slice(-6).reverse().map((d) => (
            <div key={d.id} className="suggest-row">
              <span className="chip soft" style={{ color: 'var(--accent)' }}>{d.kind.replace('_', ' ')}</span>
              <span style={{ flex: 1, minWidth: 0 }}>{d.scope && <><ScopeLink scope={d.scope} />: </>}<span className="muted">{d.reason}</span></span>
              <button className="btn sm" onClick={() => api.approve(d.id, true)}>Apply</button>
              <button className="btn sm ghost" onClick={() => api.approve(d.id, false)}>Reject</button>
            </div>
          ))}
        </section>
      )}

      <div className="toolbar">
        <div className="seg">
          <button className={sev === 'all' ? 'on' : ''} onClick={() => setSev('all')}>All {total}</button>
          {SEV_ORDER.map((k) => <button key={k} className={sev === k ? 'on' : ''} onClick={() => setSev(k)}><span className={`sev-dot sev-${k}`} />{SEVERITY[k].label} {b.counts[k]}</button>)}
        </div>
        <label className="row mono muted" style={{ gap: 6 }}><input type="checkbox" checked={flat} onChange={(e) => setFlat(e.target.checked)} />show grouped findings one by one</label>
        <span style={{ flex: 1 }} />
        <input className="input" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 220 }} />
      </div>
      <FindingList items={items} empty={<Empty title={total ? 'No findings match.' : 'Nothing needs attention.'}>{total ? 'Clear the filter to see them all.' : 'Findings appear here when a monitor escalates.'}</Empty>} />
      {(b.raw_counts.ACT + b.raw_counts.LOOK + b.raw_counts.WATCH) > items.length && !flat && !q && sev === 'all' && (
        <div className="muted" style={{ fontSize: 12.5, marginTop: 10 }}><Icon name="layers" size={13} /> {b.raw_counts.ACT + b.raw_counts.LOOK + b.raw_counts.WATCH} findings in {items.length} rows after grouping similar ones.</div>
      )}
    </div>
  )
}
