import React, { useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import type { Investigation, InvestigationNode, Snapshot } from '../types'
import { ClaimList, Empty, fmtTime, Icon, ScopeLink } from '../components/ui'

const GLYPH: Record<string, string> = { done: '✓', partial: '◐', running: '◐', pending: '', stopped: '–', failed: '!' }
const ROLES = ['timeline', 'communication', 'exposure', 'action_verifier', 'response', 'goal_check', 'trigger', 'deep_dive', 'skeptic']

export function Investigations({ s }: { s: Snapshot }) {
  const sel = useStore((x) => x.selectedInvestigation)
  const select = useStore((x) => x.selectInvestigation)
  const invs = [...s.investigations].reverse()
  const inv = invs.find((i) => i.id === sel) ?? invs[0]
  return (
    <div className="fade-in two-col" style={{ gridTemplateColumns: '320px minmax(0, 1fr)', gap: 18, marginTop: 0 }}>
      <div>
        <div className="page-title" style={{ marginBottom: 4 }}>Investigations</div>
        <div className="muted" style={{ marginBottom: 14 }}>Machine cognition, made visible. Each tree is a question broken into investigator roles.</div>
        <AskBox />
        <div className="stack" style={{ gap: 8, marginTop: 12 }}>
          {invs.map((i) => (
            <button key={i.id} className="card" onClick={() => select(i.id)}
              style={{ textAlign: 'left', cursor: 'pointer', borderColor: inv?.id === i.id ? 'var(--ink)' : undefined }}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <span className="label" style={{ color: i.status === 'running' ? 'var(--st-inferred)' : undefined }}>{i.status === 'open' ? 'starting' : i.status}</span>
                <span className="mono muted">{fmtTime(i.opened, true)}</span>
              </div>
              <div className="serif" style={{ fontSize: 15, lineHeight: 1.3, marginTop: 3 }}>{i.title}</div>
              <div className="row" style={{ gap: 3, marginTop: 6 }}>
                {i.nodes.map((n) => <span key={n.id} className={`node-icon ni-${n.status}`} style={{ width: 13, height: 13, fontSize: 8 }}>{GLYPH[n.status]}</span>)}
                {i.pinned && <span className="mono muted" style={{ marginLeft: 6 }}>pinned</span>}
              </div>
            </button>
          ))}
          {!invs.length && <Empty title="No investigations yet.">They open when SwarmFrame asks a question about a finding, or when you do.</Empty>}
        </div>
      </div>
      <div>{inv ? <Tree s={s} inv={inv} /> : null}</div>
    </div>
  )
}

function AskBox() {
  const [text, setText] = useState('')
  return (
    <form className="stack" style={{ gap: 6 }} onSubmit={(e) => { e.preventDefault(); if (text.trim()) { api.question(text.trim()); setText('') } }}>
      <textarea className="input" rows={2} placeholder="Ask a custom question, e.g. “Did anyone act on the operator's message?”"
        value={text} onChange={(e) => setText(e.target.value)} />
      <button className="btn primary" type="submit" style={{ alignSelf: 'flex-start' }}>Open investigation</button>
    </form>
  )
}

function Tree({ s, inv }: { s: Snapshot; inv: Investigation }) {
  const [role, setRole] = useState('deep_dive')
  const q = s.questions.find((x) => x.id === inv.question_id)
  const roots = inv.nodes.filter((n) => !n.parent)
  const kids = (id: string) => inv.nodes.filter((n) => n.parent === id)
  return (
    <section className="panel">
      <div style={{ padding: '20px 22px 8px' }}>
        <div className="row" style={{ gap: 8 }}>
          <span className="label">Question</span>
          <span className="mono muted">asked by {q?.requested_by ?? 'executive'} · scope <ScopeLink scope={inv.scope} /></span>
          <span className="mono muted" style={{ marginLeft: 'auto' }}>${inv.spent_usd.toFixed(3)} of ${inv.budget_usd.toFixed(2)}</span>
        </div>
        <div className="display" style={{ fontSize: 26, lineHeight: 1.2, margin: '6px 0 10px' }}>{inv.title}</div>
        {inv.conclusion && (
          <div className="card" style={{ background: 'var(--sunken)', borderColor: 'transparent' }}>
            <div className="label" style={{ marginBottom: 3 }}>Conclusion · {q?.answer?.status?.replace('_', ' ')}</div>
            <div className="italic" style={{ fontSize: 18, lineHeight: 1.4 }}>{inv.conclusion}</div>
            {q?.answer?.unresolved?.length ? (
              <div style={{ marginTop: 8 }}>
                <div className="label">Unresolved</div>
                {q.answer.unresolved.map((u, i) => <div key={i} style={{ fontSize: 13, color: 'var(--ink-2)' }}>· {u}</div>)}
              </div>
            ) : null}
          </div>
        )}
        <div className="row" style={{ gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
          <button className="btn sm" onClick={() => api.invAction(inv.id, 'deeper')}>Investigate deeper</button>
          <button className="btn sm" onClick={() => api.invAction(inv.id, 'alternative')}>Request alternative explanation</button>
          <span className="row" style={{ gap: 4 }}>
            <select className="input" style={{ width: 150, padding: '3px 26px 3px 8px', fontSize: 12 }} value={role} onChange={(e) => setRole(e.target.value)}>
              {ROLES.map((r) => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}
            </select>
            <button className="btn sm" onClick={() => api.invAction(inv.id, 'launch', { role })}>Launch investigator</button>
          </span>
          <button className="btn sm" onClick={() => api.invAction(inv.id, 'pin')}><Icon name="pin" size={13} />{inv.pinned ? 'Unpin' : 'Pin finding'}</button>
          {inv.conclusion && <button className="btn sm" onClick={() => api.pin(inv.conclusion!, 'pinned_fact')}>Ask the analysts to keep this in mind</button>}
          {inv.status === 'running' && <button className="btn sm danger" onClick={() => api.invAction(inv.id, 'stop')}>Stop</button>}
        </div>
      </div>
      <div style={{ padding: '6px 22px 22px' }} className="tree">
        {roots.map((n) => <Node key={n.id} s={s} inv={inv} n={n} kids={kids} />)}
      </div>
    </section>
  )
}

function Node({ s, inv, n, kids }: { s: Snapshot; inv: Investigation; n: InvestigationNode; kids: (id: string) => InvestigationNode[] }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="tree-node">
      <div className="node-card">
        <div className="row" style={{ gap: 9 }}>
          <span className={`node-icon ni-${n.status}`}>{GLYPH[n.status]}</span>
          <span style={{ fontWeight: 600 }}>{n.title}</span>
          <span className="mono muted">{n.role.replace('_', ' ')}{n.requested_by === 'human' ? ' · by you' : ''}</span>
          <span style={{ marginLeft: 'auto' }} className="row">
            {n.tokens > 0 && <span className="mono muted">{n.tokens} tok</span>}
            {n.status === 'pending' && <button className="btn ghost sm" onClick={() => api.invAction(inv.id, 'stop', { node_id: n.id })}>Stop branch</button>}
            {n.claims.length > 0 && <button className="btn ghost sm" onClick={() => setOpen(!open)}>{open ? 'Hide' : `${n.claims.length} claims`}</button>}
          </span>
        </div>
        {n.summary && <div className="muted" style={{ fontSize: 13, margin: '4px 0 0 29px' }}>{n.summary}</div>}
        {open && n.claims.length > 0 && <div style={{ margin: '8px 0 0 25px' }}><ClaimList ids={n.claims} claims={s.claims} compact /></div>}
      </div>
      {kids(n.id).map((k) => <Node key={k.id} s={s} inv={inv} n={k} kids={kids} />)}
    </div>
  )
}
