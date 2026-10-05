import React, { useEffect, useState } from 'react'
import { api, get } from '../api'
import { useStore } from '../store'
import { famColor, fmtTime, Icon, StatusChip } from './ui'
import { EvidenceChip, findingAction, SevMark, SourceList } from './findings'
import { Tip, useTerms } from './kit'
import { AXES } from '../words'

export function EvidenceDrawer() {
  const drawer = useStore((s) => s.drawer)
  const close = () => useStore.getState().openDrawer(null)
  const [data, setData] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    setData(null); setErr(null)
    if (!drawer) return
    const url = drawer.kind === 'claim' ? `/api/claim/${drawer.id}` : drawer.kind === 'event' ? `/api/event/${encodeURIComponent(drawer.id)}`
      : drawer.kind === 'entity' ? `/api/entity/${encodeURIComponent(drawer.id)}`
        : drawer.kind === 'finding' ? `/api/incident/${encodeURIComponent(drawer.id)}` : null
    if (url) get(url).then(setData).catch((e) => setErr(String(e)))
  }, [drawer])
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && close()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [])
  if (!drawer) return null
  return (
    <>
      <div className="drawer-backdrop" onClick={close} />
      <aside className="drawer" role="dialog" aria-label="Evidence">
        <div className="drawer-head row">
          <span className="label">{drawer.kind === 'claim' ? 'Claim & evidence' : drawer.kind === 'event' ? 'Evidence event' : drawer.kind === 'finding' ? 'Finding' : 'Entity'}</span>
          <button className="btn ghost icon-btn" style={{ marginLeft: 'auto' }} onClick={close} aria-label="Close"><Icon name="x" size={16} /></button>
        </div>
        <div className="drawer-body">
          {err && <div className="muted">{err.includes('404') ? (drawer.kind === 'finding' ? 'This finding is no longer open.' : 'This evidence is not visible at the current replay time.') : err}</div>}
          {!data && !err && <div className="muted">Loading…</div>}
          {data && drawer.kind === 'claim' && <ClaimView c={data} />}
          {data && drawer.kind === 'event' && <EventView e={data} />}
          {data && drawer.kind === 'entity' && <EntityView d={data} />}
          {data && drawer.kind === 'finding' && <FindingView f={data} />}
        </div>
      </aside>
    </>
  )
}

function ClaimView({ c }: { c: any }) {
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="row" style={{ gap: 8 }}>
        <StatusChip status={c.status} soft={false} />
        <span className="mono muted">confidence {Math.round(c.confidence * 100)}% · by {c.author} · {fmtTime(c.ts, true)}</span>
      </div>
      <div className="display" style={{ fontSize: 23, lineHeight: 1.3 }}>{c.statement}</div>
      <div className="card" style={{ background: 'var(--sunken)', borderColor: 'transparent', fontSize: 13 }}>
        {STATUS_EXPLAIN[c.status]}
      </div>
      <Section title={`Supporting evidence (${c.support_detail.length})`}>
        {c.support_detail.length ? c.support_detail.map((e: any) => <EvidenceItem key={e.id} e={e} />)
          : <div className="muted">No evidence attached{c.status === 'INFERRED' ? ' — this is an interpretation, not an observation.' : '.'}</div>}
      </Section>
      {c.counter_detail.length > 0 && <Section title={`Counterevidence (${c.counter_detail.length})`}>{c.counter_detail.map((e: any) => <EvidenceItem key={e.id} e={e} />)}</Section>}
      {c.related.length > 0 && (
        <Section title="Other claims about this scope">
          {c.related.map((r: any) => (
            <div key={r.id} className="row clickable" style={{ alignItems: 'flex-start', padding: 4, borderRadius: 6 }}
              onClick={() => useStore.getState().openDrawer({ kind: 'claim', id: r.id })}>
              <StatusChip status={r.status} /><span style={{ fontSize: 13 }}>{r.statement}</span>
            </div>
          ))}
        </Section>
      )}
      <button className="btn" style={{ alignSelf: 'flex-start' }} onClick={() => api.pin(c.statement, 'pinned_fact', [c.id])}><Icon name="pin" size={14} />Ask the analysts to keep this in mind</button>
    </div>
  )
}

const STATUS_EXPLAIN: Record<string, string> = {
  OBSERVED: 'Directly visible in the cited evidence. A verifier checked that every cited event exists and precedes the replay horizon.',
  DERIVED: 'Computed from observed evidence (counts, comparisons, searches). The inputs are cited.',
  SELF_REPORTED: 'Something an agent said about itself. Agent-written content is untrusted evidence.',
  INFERRED: 'An interpretation. Never silently treated as fact; it stays inferred until a deterministic check promotes it.',
  CONTRADICTED: 'A critic or a later finding contradicts an earlier claim.',
  UNKNOWN: 'An open point the available evidence cannot settle, or an alternative explanation worth testing.',
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div><div className="label" style={{ marginBottom: 6 }}>{title}</div><div className="stack" style={{ gap: 8 }}>{children}</div></div>
}

function EvidenceItem({ e }: { e: any }) {
  if (e.kind === 'claim') return (
    <div className="row clickable card" onClick={() => useStore.getState().openDrawer({ kind: 'claim', id: e.id })}><StatusChip status={e.status} /><span>{e.statement}</span></div>
  )
  return <div className="card"><EventBody e={e} /></div>
}

function EventBody({ e }: { e: any }) {
  return (
    <>
      <div className="row" style={{ gap: 8 }}>
        <span style={{ width: 4, alignSelf: 'stretch', borderRadius: 2, background: famColor(e.family) }} />
        <div style={{ flex: 1 }}>
          <div><b>{e.actor}</b> <span className="mono muted">{e.action}</span> {e.object && <span className="ink2">→ {e.object}</span>}</div>
          <div className="mono muted">{fmtTime(e.ts, true)} UTC · {e.family}{e.note ? ` · ${String(e.note).slice(0, 80)}` : ''}</div>
        </div>
        <button className="btn ghost sm" onClick={() => useStore.getState().openDrawer({ kind: 'event', id: e.id })}>Open</button>
      </div>
      {e.untrusted_text && (
        <>
          <div className="untrusted-label" style={{ marginTop: 8 }}><span className="label" style={{ color: 'var(--st-self)' }}>Agent-written · untrusted</span>
            <span className="mono muted">{e.artifact_meta?.size} chars · sha {e.artifact_meta?.fingerprint}</span></div>
          <div className="untrusted">{e.untrusted_text}</div>
        </>
      )}
      {[['reasoning_text', 'Its private reasoning'], ['rationale_text', 'Its stated rationale'], ['answer_text', 'The answer it got']].map(([k, l]) => e[k] && (
        <React.Fragment key={k}>
          <div className="untrusted-label" style={{ marginTop: 8 }}><span className="label" style={{ color: 'var(--st-self)' }}>{l} · agent-written · untrusted</span></div>
          <div className="untrusted">{e[k]}</div>
        </React.Fragment>
      ))}
    </>
  )
}

function EventView({ e }: { e: any }) {
  return (
    <div className="stack" style={{ gap: 14 }}>
      <EventBody e={e} />
      <Section title="Provenance">
        <div className="kv mono" style={{ fontSize: 11.5 }}>
          <span className="muted">source</span><span>{e.source}</span>
          <span className="muted">locator</span><span>{e.locator}</span>
          <span className="muted">event id</span><span style={{ wordBreak: 'break-all' }}>{e.id}</span>
          {e.artifact_meta && <><span className="muted">artifact</span><span>{e.artifact_meta.provenance} · labels {e.artifact_meta.labels.join(', ') || 'none'}</span></>}
        </div>
      </Section>
      {e.actor_id && <button className="btn" style={{ alignSelf: 'flex-start' }} onClick={() => useStore.getState().openDrawer({ kind: 'entity', id: e.actor_id })}>Open {e.actor}</button>}
    </div>
  )
}

function EntityView({ d }: { d: any }) {
  const e = d.entity
  const max = Math.max(1, ...d.families.map((f: any) => f.n))
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div>
        <div className="mono muted">{e.type} · {e.group ?? 'no group'} · identity {e.identity_confidence}</div>
        <div className="display" style={{ fontSize: 28 }}>{e.label}</div>
      </div>
      <div className="row" style={{ gap: 6 }}>
        <button className="btn sm" onClick={() => api.directive('focus', `${e.type === 'resource' ? 'resource' : 'agent'}:${e.id}`, { weight: 1.5 }, 'focus requested by a human')}>Focus monitors here</button>
        <button className="btn sm" onClick={() => api.question(`What is ${e.label} doing, and does it need attention?`, `${e.type === 'resource' ? 'resource' : 'agent'}:${e.id}`)}>Ask about {e.label}</button>
      </div>
      <Section title="Activity by workstream">
        {d.families.map((f: any) => (
          <div key={f.family} className="row" style={{ gap: 8 }}>
            <span style={{ width: 80, fontSize: 12.5 }}>{f.family}</span>
            <div className="bar-track" style={{ flex: 1 }}><div className="bar-fill" style={{ width: `${(f.n / max) * 100}%`, background: famColor(f.family) }} /></div>
            <span className="num" style={{ width: 40 }}>{f.n}</span>
          </div>
        ))}
      </Section>
      {d.observations.length > 0 && <Section title="Watcher observations">
        {d.observations.slice().reverse().map((o: any) => <div key={o.id} className="card" style={{ fontSize: 13 }}><span className="mono muted">{fmtTime(o.window_end, true)} · {o.watcher}</span><div>{o.title}</div></div>)}
      </Section>}
      <Section title="Recent events">
        {d.recent.map((r: any) => (
          <div key={r.id} className="row clickable" style={{ padding: '4px 6px', borderRadius: 6 }} onClick={() => useStore.getState().openDrawer({ kind: 'event', id: r.id })}>
            <span className="mono muted" style={{ width: 70 }}>{fmtTime(r.ts, true)}</span>
            <span className="mono" style={{ width: 130 }}>{r.action}</span>
            <span className="ink2" style={{ fontSize: 12.5 }}>{r.object}{r.note ? ` · ${String(r.note).slice(0, 60)}` : ''}</span>
          </div>
        ))}
      </Section>
    </div>
  )
}

function FindingView({ f }: { f: any }) {
  const t = useTerms()
  const select = useStore((s) => s.selectInvestigation)
  const open = useStore((s) => s.openDrawer)
  const inv = f.investigation_detail
  const act = (a: string) => findingAction(f.id, a).then(() => { if (a === 'dismiss' || a === 'snooze') open(null) })
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <SevMark sev={f.severity} />
        <span className={`fresh fresh-${f.fresh}`}>{f.fresh_text}</span>
        <EvidenceChip kind={f.evidence} />
        {f.count > 1 && <span className="mono muted">{f.count} similar findings</span>}
      </div>
      <div className="display" style={{ fontSize: 25, lineHeight: 1.25 }}>{f.headline}</div>
      {f.detail && <div className="muted">{f.detail}</div>}
      {f.explain && (f.explain.why || f.explain.what !== f.headline) && (
        <div className="explain-box">
          <div className="label">In plain words</div>
          {f.explain.what && f.explain.what !== f.headline && <p>{f.explain.what}</p>}
          {f.explain.why && <p><b>Why it might matter.</b> {f.explain.why}</p>}
          {f.explain.benign && <p><b>The innocent reading.</b> {f.explain.benign}</p>}
          {f.explain.check && <p><b>What to check.</b> {f.explain.check}</p>}
        </div>
      )}
      <div className="next-box"><span className="next-k">Next</span>{f.next}</div>
      {f.cites?.length > 0 && (
        <Section title={`Sources (${f.cites.length})`}>
          <div className="muted" style={{ fontSize: 12.5, marginTop: -2 }}>What this finding rests on: the claims the watchers and analysts made, and the recorded events under them. Open any to check it.</div>
          <SourceList cites={f.cites} />
        </Section>
      )}
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        {inv && <button className="btn primary" onClick={() => select(inv.id)}>{inv.status === 'running' || inv.status === 'open' ? 'Open the investigation' : 'Read the investigation'} <Icon name="arrow" size={13} /></button>}
        {(!inv || (inv.status !== 'running' && inv.status !== 'open')) && <button className="btn" onClick={() => act('investigate')}><Icon name="investigations" size={14} />Investigate</button>}
        <button className="btn" onClick={() => useStore.getState().showInWorld(f.scope)}><Icon name="globe" size={14} />Show me in the World</button>
        <button className="btn" onClick={() => act('watch')}><Icon name="attention" size={14} />Watch more closely</button>
        <button className="btn ghost" onClick={() => act(f.pinned ? 'unpin' : 'pin')}><Icon name="pin" size={14} />{f.pinned ? 'Unpin' : 'Pin'}</button>
        <button className="btn ghost" onClick={() => act('snooze')}><Icon name="snooze" size={14} />Snooze</button>
        <button className="btn ghost danger" onClick={() => act('dismiss')}><Icon name="x" size={14} />{f.count > 1 ? `Dismiss all ${f.count}` : 'Dismiss'}</button>
      </div>
      {(f.needs_ack || f.acknowledged) && (
        <div className={`ack-inline ${f.overdue ? 'overdue' : ''}`}>
          {f.acknowledged ? <span className="muted">Acknowledged by {f.acknowledged_by ?? 'you'}.</span>
            : <><span>{f.overdue ? 'Escalated and waiting past the agreed time.' : 'Escalated by the team; waiting for your receipt.'}</span>
              <button className="btn sm accent" onClick={() => act('ack')}>Acknowledge</button></>}
          {f.level !== 'PAGE' && <button className="btn sm ghost" onClick={() => findingAction(f.id, 'escalate', f.headline, f.level === 'ALERT' ? 'PAGE' : 'ALERT')}>{f.level === 'ALERT' ? 'Raise to act now' : 'Raise to act'}</button>}
        </div>
      )}
      {f.history && f.history.length > 0 && (
        <Section title="How it got here">
          <div className="muted" style={{ fontSize: 12.5, marginBottom: 6 }}>Seen by {f.views?.length ?? 0} independent {(f.views?.length ?? 0) === 1 ? 'source' : 'sources'}: {(f.views ?? []).map((v: string) => v.replace('monitor:', 'watcher ').replace('role:', '').replace('_', ' ')).join(', ')}.</div>
          <ol className="case-history">
            {f.history.slice().reverse().map((h: any, i: number) => (
              <li key={i} className={h.held ? 'held' : ''}>
                <span className={`chip soft lv-${h.level}`}><span className="dot" />{h.held ? `held at ${h.level.toLowerCase()}` : h.level.toLowerCase()}</span>
                <span className="ch-text">{h.reason}{h.held ? ` — ${h.held}` : ''}</span>
                <span className="mono muted ch-by">{h.by} · {new Date(h.ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
              </li>
            ))}
          </ol>
        </Section>
      )}
      {inv?.conclusion && (
        <Section title="What the investigation found">
          <div className="italic" style={{ fontSize: 16, lineHeight: 1.45 }}>{inv.conclusion}</div>
        </Section>
      )}
      {f.group_rows && (
        <Section title={`The ${f.group_rows.length} findings in this group`}>
          {f.group_rows.map((m: any) => (
            <div key={m.id} className="row clickable member" onClick={() => open({ kind: 'finding', id: m.id })}>
              <SevMark sev={m.severity} /><span style={{ flex: 1, fontSize: 13.5 }}>{m.headline}</span>
              <span className="mono muted">{m.fresh_text}</span>
            </div>
          ))}
        </Section>
      )}
      <Section title="How serious, on each axis">
        <div className="axes">
          {AXES.filter((a) => a.key !== 'coordination' || useStore.getState().snap?.brief?.identities !== false).map((a) => {
            const v = f.axes?.[a.key] ?? 0
            return (
              <Tip key={a.key} text={a.help(t)} inline={false}>
                <div className="axis">
                  <span className="axis-l">{a.label}</span>
                  <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.max(3, v * 100)}%`, background: v > 0.6 ? 'var(--sev-act)' : v > 0.3 ? 'var(--sev-look)' : 'var(--ink-4)' }} /></div>
                  <span className="mono muted axis-v">{v >= 0.6 ? 'high' : v >= 0.3 ? 'medium' : v > 0 ? 'low' : 'none'}</span>
                </div>
              </Tip>
            )
          })}
        </div>
      </Section>
      {f.claims?.length > 0 && (
        <Section title="Evidence">
          {f.claims.map((c: any) => (
            <div key={c.id} className="row clickable card" style={{ alignItems: 'flex-start' }} onClick={() => open({ kind: 'claim', id: c.id })}>
              <StatusChip status={c.status} /><span style={{ fontSize: 13.5 }}>{c.statement}</span>
            </div>
          ))}
        </Section>
      )}
      {f.scope && <div className="mono muted" style={{ fontSize: 11 }}>scope {f.label || f.scope} · {f.reports} monitor report{f.reports === 1 ? '' : 's'} · opened {fmtTime(f.opened, true)}</div>}
    </div>
  )
}
