import { Overview } from '../components/Overview'
import React, { useState } from 'react'
import { api, post } from '../api'
import { useStore } from '../store'
import type { DashState, GlanceStat, Snapshot } from '../types'
import { fmtDay, fmtNum, fmtTime, Icon, Toggle } from '../components/ui'
import { dashOps, Tip, useTerms } from '../components/kit'
import { atLeast, FindingList, findingAction } from '../components/findings'
import { Sparkline } from '../primitives/charts'
import { GLANCE_HELP, SEVERITY } from '../words'
import { PageEditMenu, PageGrid } from './Views'
import { fieldFrom, SwarmField } from '../components/SwarmField'

// the World is three.js: load it only when the Brief shows it
const BriefWorld = React.lazy(() => import('./World').then((m) => ({ default: m.BriefWorld })))

export function startReplay(s: Snapshot) {
  const a = s.autoplay
  const scale = a === 'max' ? 1e12 : typeof a === 'number' ? a : 3600
  api.clock('scale', Math.min(scale, 60 * s.clock.window_s)).then(() => api.clock('play'))
}

export function Brief({ s }: { s: Snapshot }) {
  const dash = useStore((x) => x.dash)
  const setRoute = useStore((x) => x.setRoute)
  const [edit, setEdit] = useState(false)
  const [settings, setSettings] = useState(false)
  const b = s.brief
  const page = dash?.spec.pages.find((p) => p.id === 'brief')
  const cfg = dash?.spec.brief
  if (!b || !dash || !page || !cfg) return <div className="skeleton" style={{ height: 320 }} />
  const notStarted = !s.clock.live && s.clock.paused && !s.population.total_events_seen
  const waiting = s.clock.live && !s.population.total_events_seen
  const items = b.items.filter((x) => atLeast(x.severity, cfg.min_severity))
  const shown = items.slice(0, cfg.attention_rows)
  const spanYears = s.clock.end && s.clock.start ? (+new Date(s.clock.end) - +new Date(s.clock.start)) > 300 * 86400e3 : false
  const showWorld = cfg.world !== false && !!s.world
  const ago = b.updated ? Math.max(0, Math.round((+new Date(s.clock.now) - +new Date(b.updated)) / 60000)) : null
  const toAck = b.items.filter((x) => x.needs_ack)
  const proposals = s.approvals?.pending ?? []
  const decide = async (id: string, action: 'approve' | 'decline') => {
    try { await post(`/api/agents/proposal/${encodeURIComponent(id)}`, { action }); useStore.getState().showToast(action === 'approve' ? 'Approved; applies between cycles' : 'Declined') }
    catch (e: any) { useStore.getState().showToast(String(e.message || e)) }
  }

  return (
    <div className="brief-page fade-in">
      {toAck.length > 0 && (
        <section className={`ack-band ${toAck.some((x) => x.overdue) ? 'overdue' : ''}`} aria-live="polite">
          <div className="ack-head">
            <span className="ack-title"><Icon name="flag" size={14} />{toAck.length === 1 ? 'A finding needs your acknowledgement' : `${toAck.length} findings need your acknowledgement`}</span>
            <span className="ack-sub">{toAck.some((x) => x.overdue) ? 'Some have waited past the agreed time.' : 'Escalated by the team; take receipt or send it back.'}</span>
          </div>
          {toAck.slice(0, 4).map((x) => (
            <div key={x.id} className="ack-row">
              <span className={`chip soft lv-${x.level}`}><span className="dot" />{x.level === 'PAGE' ? 'act now' : 'act'}</span>
              <button className="link ack-text" onClick={() => useStore.getState().openDrawer({ kind: 'finding', id: x.id })}>{x.headline}</button>
              <span className="mono muted ack-by">{x.history?.slice().reverse().find((h) => !h.held && (h.level === 'ALERT' || h.level === 'PAGE'))?.by ?? x.owner ?? ''}{x.overdue ? ' · overdue' : ''}</span>
              <button className="btn sm accent" onClick={() => findingAction(x.id, 'ack', x.headline)}>Acknowledge</button>
            </div>
          ))}
          {toAck.length > 4 && <button className="link" onClick={() => setRoute('attention')}>and {toAck.length - 4} more</button>}
        </section>
      )}
      {proposals.length > 0 && (
        <section className="ack-band proposals" aria-live="polite">
          <div className="ack-head">
            <span className="ack-title" style={{ color: 'var(--st-derived)' }}><Icon name="layers" size={14} />{proposals.length === 1 ? 'The team proposes a change' : `The team proposes ${proposals.length} changes`}</span>
            <span className="ack-sub">Outside what it may do alone; nothing applies until you decide.</span>
          </div>
          {proposals.slice(0, 3).map((p) => (
            <div key={p.id} className="ack-row">
              <span className="chip soft" style={{ color: 'var(--st-derived)' }}>{p.kind}</span>
              <span className="ack-text" title={p.reasons.join('; ')}><b>{p.describe}</b>{p.reasons[0] ? ` — ${p.reasons[0]}` : ''}</span>
              <span className="mono muted ack-by">{p.by} · {p.note.replace('needs a person: ', '')}</span>
              <span className="row" style={{ gap: 6 }}><button className="btn sm accent" onClick={() => decide(p.id, 'approve')}>Approve</button><button className="btn sm ghost" onClick={() => decide(p.id, 'decline')}>Decline</button></span>
            </div>
          ))}
        </section>
      )}
      <section className="status-block">
        {!notStarted && <SwarmField input={fieldFrom(s)} />}
        <div className="status-top">
          <span className="label">{s.source.title} · {fmtDay(s.clock.now, spanYears)}{!spanYears && ` · ${fmtTime(s.clock.now)}`}</span>
          <PageEditMenu page={page} edit={edit} setEdit={setEdit}
            extra={[{ label: 'Glance numbers, attention list, World…', icon: 'configure', onClick: () => setSettings(true) }]} />
        </div>
        {notStarted && s.autoplay && !s.clock.index ? (
          <div className="cta">
            <div className="status">Starting the replay…</div>
            <p className="status-sub">SwarmFrame reads the recording as it unfolds; the first findings appear within seconds.</p>
            <button className="btn lg" onClick={() => startReplay(s)}><Icon name="play" size={16} />Play</button>
          </div>
        ) : notStarted ? (
          <div className="cta">
            <div className="status">The replay is ready.</div>
            <p className="status-sub">Nothing has happened yet: press play and SwarmFrame reads the recording as it unfolds.</p>
            <button className="btn accent lg" onClick={() => startReplay(s)}><Icon name="play" size={16} />Play the replay</button>
          </div>
        ) : waiting ? (
          <div className="cta">
            <div className="status">Waiting for the first events…</div>
            <p className="status-sub">{s.stream ? <>{s.stream.received} received so far. Post events to <span className="mono">/ingest/events</span>{!s.stream.feed && <>, or <button className="link" onClick={() => post('/api/stream/demo')}>play the sample swarm</button></>}.</> : 'Agents report here as soon as they start.'}</p>
          </div>
        ) : (
          <>
            <h1 className="status">{b.status}</h1>
            {b.status_detail && <p className="status-detail">{b.status_detail}</p>}
            <p className="status-sub">
              <span className={`lead-dot ${b.counts.ACT ? 'act' : b.counts.LOOK ? 'look' : 'ok'}`} />
              {b.attention_line}
              {ago !== null && <span className="muted">{'· '}{ago < 1 ? 'updated just now' : ago < 120 ? `updated ${ago} min ago` : ago < 48 * 60 ? `updated ${Math.round(ago / 60)} h ago` : `as of ${fmtDay(b.updated, spanYears)}`}</span>}
            </p>
          </>
        )}
      </section>

      {!notStarted && (
        <div className="glance" style={{ gridTemplateColumns: `repeat(${Math.max(2, cfg.glance.length)}, minmax(0, 1fr))` }}>
          {cfg.glance.filter((k) => b.glance[k]).map((k) => <Glance key={k} id={k} g={b.glance[k]} onClick={() => {
            const to: Record<string, any> = { attention: 'attention', watching: 'attention', investigating: 'investigations', coverage: 'hood', approvals: 'control' }
            if (to[k]) setRoute(to[k])
          }} />)}
        </div>
      )}

      {!notStarted && b.overview && cfg.overview !== false && <Overview o={b.overview} />}

      {!notStarted && (cfg.attention_rows > 0 || showWorld) && (
      <div className={showWorld && cfg.attention_rows > 0 ? 'brief-split' : ''}>
      {cfg.attention_rows > 0 && (
        <section className="block">
          <div className="block-head">
            <h2 className="h-section">Needs attention</h2>
            <span className="sev-counts">
              {(['ACT', 'LOOK', 'WATCH'] as const).map((k) => b.counts[k] > 0 && (
                <Tip key={k} text={SEVERITY[k].help}><span className={`sev-count sev-${k}`}><i />{b.counts[k]} {SEVERITY[k].label.toLowerCase()}</span></Tip>
              ))}
            </span>
            <span style={{ flex: 1 }} />
            {items.length > shown.length && <button className="link" onClick={() => setRoute('attention')}>See all {items.length} <Icon name="arrow" size={13} /></button>}
          </div>
          <FindingList items={shown} empty={<div className="all-clear"><Icon name="check" size={16} />Nothing needs attention{cfg.min_severity !== 'WATCH' ? ` at ${SEVERITY[cfg.min_severity].label} or above` : ''}.</div>} />
        </section>
      )}
      {showWorld && (
        <React.Suspense fallback={<div className="skeleton" style={{ height: 440 }} />}><BriefWorld s={s} /></React.Suspense>
      )}
      </div>
      )}

      {(page.panels.length > 0 || edit) && !notStarted && <PageGrid s={s} page={page} edit={edit} />}
      {!page.panels.length && edit && (
        <div className="empty-page"><button className="btn" onClick={() => useStore.getState().setStudioOpen(true, 'add', 'brief')}><Icon name="plus" size={14} />Add a panel to the Brief</button></div>
      )}

      {cfg.show_changes && b.changes.length > 0 && !notStarted && (
        <section className="block changes">
          <div className="block-head"><h2 className="h-section">What changed</h2><span style={{ flex: 1 }} />
            <button className="link" onClick={() => setRoute('investigations')}>Investigations <Icon name="arrow" size={13} /></button></div>
          <div className="change-list">
            {b.changes.slice(0, 5).map((c) => (
              <div key={c.id} className="change">
                <span className="mono muted">{fmtTime(c.ts)}</span>
                <span className={`change-k ck-${c.kind}`}>{c.label}</span>
                <span className="change-t">{c.text}</span>
              </div>
            ))}
          </div>
        </section>
      )}
      {settings && <BriefSettings dash={dash} onClose={() => setSettings(false)} />}
    </div>
  )
}

function Glance({ id, g, onClick }: { id: string; g: GlanceStat; onClick: () => void }) {
  const clickable = ['attention', 'watching', 'investigating', 'coverage', 'approvals'].includes(id)
  const hot = (id === 'attention' || id === 'approvals') && g.value > 0
  return (
    <Tip text={GLANCE_HELP[id] ?? ''} inline={false}>
      <div className={`glance-tile ${clickable ? 'clickable' : ''} ${hot ? 'hot' : ''}`} onClick={clickable ? onClick : undefined}>
        <div className="g-label">{g.label}</div>
        <div className="g-v">{fmtNum(g.value)}{g.unit && <small>{g.unit}</small>}</div>
        <div className="g-sub">{g.sub}</div>
        <div className="g-trace">{g.series.length > 2 && <Sparkline values={g.series} width={200} height={30} fluid area color={hot ? 'var(--accent)' : 'var(--ink-3)'} />}</div>
      </div>
    </Tip>
  )
}

function BriefSettings({ dash, onClose }: { dash: DashState; onClose: () => void }) {
  const cfg = dash.spec.brief
  const terms = useTerms()
  const set = (op: Record<string, any>, msg: string) => dashOps([{ op: 'set_brief', ...op }], msg, msg)
  const avail = Object.keys(dash.glance)
  const toggle = (k: string) => {
    const on = cfg.glance.includes(k)
    const next = on ? cfg.glance.filter((x) => x !== k) : [...cfg.glance, k]
    if (next.length < 1 || next.length > 6) return
    set({ glance: next }, on ? 'Removed a glance number' : 'Added a glance number')
  }
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 'min(560px, 100%)' }} onClick={(e) => e.stopPropagation()}>
        <div className="studio-head"><div style={{ flex: 1 }}><div className="label">The Brief</div><div className="display" style={{ fontSize: 24 }}>Glance numbers, attention list and the World</div></div>
          <button className="btn ghost icon-btn" onClick={onClose}><Icon name="x" size={16} /></button></div>
        <div className="studio-body stack" style={{ gap: 18 }}>
          <div>
            <div className="label" style={{ marginBottom: 8 }}>Glance numbers (1 to 6, in this order)</div>
            <div className="stack" style={{ gap: 6 }}>
              {avail.map((k) => (
                <label key={k} className="check-row">
                  <input type="checkbox" checked={cfg.glance.includes(k)} onChange={() => toggle(k)} />
                  <span style={{ fontWeight: 500 }}>{k === 'active' ? `${terms.agent}s active` : dash.glance[k]}</span>
                  <span className="muted" style={{ fontSize: 12 }}>{GLANCE_HELP[k]}</span>
                </label>
              ))}
            </div>
          </div>
          <div>
            <div className="label" style={{ marginBottom: 8 }}>Attention list</div>
            <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
              <span>Show up to</span>
              <div className="seg">{[0, 3, 5, 8, 12].map((n) => <button key={n} className={cfg.attention_rows === n ? 'on' : ''} onClick={() => set({ attention_rows: n }, n ? `Showing up to ${n} findings` : 'Attention list hidden')}>{n || 'none'}</button>)}</div>
            </div>
            <div className="row" style={{ gap: 12, marginTop: 10, flexWrap: 'wrap' }}>
              <span>Include</span>
              <div className="seg">{(['ACT', 'LOOK', 'WATCH'] as const).map((k) => <button key={k} className={cfg.min_severity === k ? 'on' : ''} onClick={() => set({ min_severity: k }, `Showing ${SEVERITY[k].label} and above`)}>{k === 'ACT' ? 'Act only' : k === 'LOOK' ? 'Act and look' : 'Everything'}</button>)}</div>
            </div>
          </div>
          <label className="row" style={{ gap: 10 }}>
            <Toggle on={cfg.overview !== false} onChange={(v) => set({ overview: v }, v ? 'Showing what is going on' : 'Hid what is going on')} />
            <span>Show “What's going on” (every group's work and what is emerging)</span>
          </label>
          <label className="row" style={{ gap: 10 }}>
            <Toggle on={cfg.world !== false} onChange={(v) => set({ world: v }, v ? 'Showing the World on the Brief' : 'Hid the World on the Brief')} />
            <span>Show the World beside “Needs attention”</span>
          </label>
          <label className="row" style={{ gap: 10 }}>
            <Toggle on={cfg.show_changes} onChange={(v) => set({ show_changes: v }, v ? 'Showing what changed' : 'Hid what changed')} />
            <span>Show “What changed”</span>
          </label>
          {cfg.snoozed.length > 0 && (
            <div className="row" style={{ gap: 10 }}>
              <span className="muted">{cfg.snoozed.length} snoozed finding{cfg.snoozed.length > 1 ? 's' : ''}</span>
              <button className="btn sm" onClick={() => dashOps(cfg.snoozed.map((id) => ({ op: 'set_brief', unsnooze: id })), 'unsnoozed all', 'Snoozed findings are back')}>Bring them back</button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
