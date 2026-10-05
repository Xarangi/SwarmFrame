import React, { useEffect, useState } from 'react'
import { api } from './api'
import { Route, useStore } from './store'
import type { Snapshot } from './types'
import { fmtDay, fmtTime, Icon, Logo } from './components/ui'
import { estimate, fmtRate } from './components/speed'
import { dashOps, Menu, Tip, ToastHost, useTerms } from './components/kit'
import { EvidenceDrawer } from './components/EvidenceDrawer'
import { ChatDock } from './components/ChatDock'
import { Brief } from './screens/Brief'
import { Attention } from './screens/Attention'
import { Investigations } from './screens/Investigations'
import { Control } from './screens/Control'
import { UnderTheHood } from './screens/UnderTheHood'
import { Settings, lensAction } from './screens/Settings'
import { Organization } from './screens/Organization'
import { MonitorAttention } from './screens/MonitorAttention'
import { CustomPage, DesignStudio } from './screens/Views'
import { Compose } from './screens/Compose'
const World = React.lazy(() => import('./screens/World').then((m) => ({ default: m.World })))

export default function App() {
  const { snap, connected, route, setRoute, connect, dash, designing, composed } = useStore()
  const terms = useTerms()
  const chatOpen = useStore((x) => x.chatOpen)
  // wide screens keep SwarmFrame's live column docked beside the page; narrow ones slide it over
  const [wide, setWide] = useState(() => window.innerWidth >= 1280)
  useEffect(() => { const on = () => setWide(window.innerWidth >= 1280); window.addEventListener('resize', on); return () => window.removeEventListener('resize', on) }, [])
  const loading = !snap
  const composing = !loading && (!!snap!.empty || route === 'compose' || (!!snap!.session_id && composed !== snap!.session_id))
  useEffect(() => { connect() }, [connect])
  const unacked = snap?.brief?.cases?.unacknowledged ?? 0
  const overdue = snap?.brief?.cases?.overdue ?? 0
  useEffect(() => {
    const base = snap?.source?.title ? `${snap.source.title} · SwarmFrame` : 'SwarmFrame'
    document.title = unacked ? `(${unacked}) ${base}` : base
  }, [unacked, snap?.source?.title])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || document.querySelector('.menu')) return        // an open menu closes first
      const layers = document.querySelectorAll<HTMLElement>('.modal-backdrop, .drawer-backdrop')
      if (layers.length) layers[layers.length - 1].click()
    }
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [])
  useEffect(() => {
    const t = localStorage.getItem('ss.theme')
    if (t) document.documentElement.dataset.theme = t
  }, [])
  const live = snap && !snap.empty && !composing
  const pages = dash?.spec.pages ?? []
  const activity = pages.filter((p) => p.nav === 'activity')
  const top = pages.filter((p) => p.nav === 'top')
  const b = snap?.brief
  const need = b ? b.counts.ACT + b.counts.LOOK : 0
  const running = snap && !snap.empty ? snap.investigations.filter((i) => i.status === 'running' || i.status === 'open').length : 0
  const [actOpen, setActOpen] = useState(true)

  const Item = ({ id, icon, label, count, hot }: { id: Route; icon: string; label: string; count?: number; hot?: boolean }) => (
    <button className={`nav-item ${route === id && !composing ? 'active' : ''}`} onClick={() => setRoute(id)}>
      <Icon name={icon} />{label}
      {!!count && <span className={`count ${hot ? 'hot' : ''}`}>{count}</span>}
    </button>
  )
  const addPage = async () => {
    let n = 1, id = 'page'
    while (pages.some((p) => p.id === id)) id = `page_${++n}`
    const d = await dashOps([{ op: 'add_page', id, title: n > 1 ? `New page ${n}` : 'New page', description: '' }], 'added a page', 'Added a page; use Edit to fill and rename it')
    if (d) { setRoute(`page:${id}`); useStore.getState().setStudioOpen(true, 'add', id) }
  }

  return (
    <div className={`shell ${live && wide ? (chatOpen ? 'docked' : 'docked-min') : ''}`}>
      <nav className="nav">
        <div className="wordmark"><Logo /><span className="name">Swarm<em>Frame</em></span></div>
        {live && (
          <>
            <Item id="brief" icon="home" label="Brief" />
            <Item id="attention" icon="flag" label="Attention" count={need} hot={overdue > 0} />
            <Item id="world" icon="globe" label="World" />
            <button className="nav-item nav-group" onClick={() => setActOpen(!actOpen)} aria-expanded={actOpen}>
              <Icon name="activity" />Activity
              <span className={`chev-sm ${actOpen ? 'open' : ''}`}><Icon name="chevron" size={13} /></span>
            </button>
            {actOpen && (
              <div className="nav-sub">
                {activity.map((p) => (
                  <button key={p.id} className={`nav-item sub ${route === `page:${p.id}` ? 'active' : ''}`} onClick={() => setRoute(`page:${p.id}`)} aria-label={p.title}>
                    <span className="nav-text">{p.title}</span>
                  </button>
                ))}
                <button className="nav-item sub add" onClick={addPage}><Icon name="plus" size={13} />Add a page</button>
              </div>
            )}
            {top.map((p) => (
              <button key={p.id} className={`nav-item ${route === `page:${p.id}` ? 'active' : ''}`} onClick={() => setRoute(`page:${p.id}`)} title={p.description}>
                <Icon name="layers" /><span className="nav-text">{p.title}</span>
              </button>
            ))}
            <Item id="investigations" icon="investigations" label="Investigations" count={running} />
            {snap?.control && <Item id="control" icon="control" label="Control" count={snap.control.pending.length} hot />}
            <Item id="hood" icon="hood" label="Under the hood" />
            {designing && <div className="nav-note"><span className="live-dot run" />composing…</div>}
          </>
        )}
        <div className="nav-foot">
          {!loading && <button className={`nav-item ${composing ? 'active' : ''}`} onClick={() => setRoute('compose')}><Icon name="plus" />New source</button>}
          {live && <Item id="settings" icon="configure" label="Settings" />}
          {live && snap && (
            <div className="rail-readout">
              <span className="label">{snap.brief?.catalog ? 'in the record' : 'watching'}</span>
              <span className="rr-v">{(snap.brief?.catalog ? snap.brief.glance.total?.value ?? 0 : snap.population.active).toLocaleString()}<small> {terms.agent}s</small></span>
              <span className="rr-sub">{snap.source.title}</span>
            </div>
          )}
          <div className="row mono muted conn"><span className={`live-dot ${connected ? '' : 'off'}`} />{connected ? 'connected' : 'reconnecting…'}</div>
        </div>
      </nav>
      <div className="main">
        {live && <TopBar s={snap!} />}
        <main className="content">
          {loading ? <div className="loading"><Logo size={34} /><span className="mono muted">connecting…</span></div>
            : composing ? <Compose /> : snap && (
            <>
              {route === 'brief' && <Brief s={snap} />}
              {route === 'attention' && <Attention s={snap} />}
              {route === 'world' && <React.Suspense fallback={<div className="skeleton" style={{ height: '70vh' }} />}><World s={snap} /></React.Suspense>}
              {route === 'investigations' && <Investigations s={snap} />}
              {route === 'control' && <Control s={snap} />}
              {route === 'hood' && <UnderTheHood s={snap} />}
              {route === 'settings' && <Settings s={snap} />}
              {route === 'organization' && <Organization s={snap} />}
              {route === 'monitor' && <MonitorAttention s={snap} />}
              {route.startsWith('page:') && <CustomPage s={snap} pageId={route.slice(5)} />}
            </>
          )}
        </main>
      </div>
      <EvidenceDrawer />
      {live && <ChatDock docked={wide} />}
      {live && <DesignStudio s={snap!} />}
      {live && <LensDialog />}
      <ToastHost />
    </div>
  )
}

/* ------------------------------------------------------------------ top bar */
const SCALES: { v: number; l: string }[] = [
  { v: 1, l: 'Real time' }, { v: 60, l: '1 min / s' }, { v: 600, l: '10 min / s' }, { v: 3600, l: '1 hour / s' },
  { v: 21600, l: '6 hours / s' }, { v: 86400, l: '1 day / s' }, { v: 604800, l: '1 week / s' }, { v: 1e12, l: 'As fast as possible' },
]

function fmtScale(x: number): string {
  if (x >= 3600 * 24 * 10) return 'max'
  if (x >= 3600) return `${+(x / 3600).toFixed(1)} h/s`
  if (x >= 60) return `${+(x / 60).toFixed(1)} min/s`
  return `${+x.toFixed(1)}×`
}

function TopBar({ s }: { s: Snapshot }) {
  const dash = useStore((x) => x.dash)
  const c = s.clock
  const scale = (c as any).time_scale ?? c.window_s * c.speed
  const catching = (c as any).catching_up as { to: string; progress: number } | null
  const years = c.end && c.start ? (+new Date(c.end) - +new Date(c.start)) > 300 * 86400e3 : false
  const [jump, setJump] = useState(false)
  return (
    <header className="topbar">
      <div className="tb-source">
        <span className="tb-title">{dash?.spec.title || s.source.title}</span>
        {s.source.synthetic && <span className="chip soft" style={{ color: 'var(--st-self)' }}>synthetic</span>}
        {s.source.live && <span className="chip soft" style={{ color: 'var(--st-observed)' }}><span className="dot" />live</span>}
        {s.live_replay && (() => {
          const lr = s.live_replay!
          const catching = !lr.on
          const from = +new Date(lr.at) - lr.warmup_min * 60e3
          const pct = Math.max(0, Math.min(99, Math.round(((+new Date(s.clock.now) - from) / (+new Date(lr.at) - from)) * 100)))
          return (
            <Tip text={catching ? `Reading the ${lr.warmup_min} minutes before the live point fast, so the monitors know what usual looks like.` : `Replaying ${lr.label} at real time, as it happened; refreshes every ${lr.window_s} s. Change the speed from the clock menu.`}>
              <span className={`live-badge ${catching ? 'catching' : 'on'}`}><span className="dot" />{catching ? `catching up · ${pct}%` : 'live'}</span>
            </Tip>
          )
        })()}
        <Tip text={s.org.llm_mode === 'stub' ? 'Rules only: deterministic analysts, no model calls. To use Claude, start the source again from New source and choose who does the reading.' : `${s.org.llm_label?.long ?? 'Claude does the reading.'} Model calls use your Claude Code login; spend so far is under Under the hood.`}>
          <span className={`chip soft mode-chip ${s.org.llm_mode === 'stub' ? '' : 'on'}`}><span className="dot" />{s.org.llm_label?.short ?? (s.org.llm_mode === 'stub' ? 'rules only' : 'Claude')}</span>
        </Tip>
      </div>
      {dash && (
        <Menu label={<span><span className="muted">Lens</span> {dash.lens}</span>} icon="lens" align="left" variant="ghost" items={[
          ...dash.lenses.map((l) => ({ label: l, icon: l === dash.lens ? 'check' : undefined, onClick: () => l !== dash.lens && lensAction('switch', l) })),
          { sep: true, label: '' },
          { label: 'Save the current layout as…', icon: 'plus', hint: 'a lens is a named dashboard for one scenario', onClick: () => useStore.setState({ lensDialog: true, drawer: null, studioOpen: false }) },
          { label: 'Manage lenses', icon: 'configure', onClick: () => useStore.getState().setRoute('settings') },
        ]} />
      )}
      <div className="tb-clock">
        {!c.live ? (
          <>
            <button className={`btn icon-btn ${c.paused ? 'accent' : ''}`} title={c.paused ? 'Play' : 'Pause'} onClick={() => api.clock(c.paused ? 'play' : 'pause')}>
              <Icon name={c.paused ? 'play' : 'pause'} size={15} />
            </button>
            <Menu label={fmtScale(scale)} icon="" variant="ghost" items={[
              ...(s.speeds ?? []).map((o) => { const v = o.v === 'max' ? 1e12 : o.v; return { label: `${o.label} · ${fmtRate(o.v)}`, hint: [o.note, estimate(s.replay_hours, o.v)].filter(Boolean).join(' · '),
                icon: (v >= 1e12 ? c.speed >= 59 : Math.abs(scale - v) / v < 0.02) ? 'check' : undefined, onClick: () => api.clock('scale', Math.min(v, 60 * c.window_s)) } }),
              ...((s.speeds ?? []).length ? [{ sep: true, label: '' }] : []),
              ...SCALES.map((o) => ({ label: o.l, hint: estimate(s.replay_hours, o.v), icon: (o.v >= 1e12 ? c.speed >= 59 : Math.abs(scale - o.v) / o.v < 0.02) ? 'check' : undefined,
                onClick: () => api.clock('scale', Math.min(o.v, 60 * c.window_s)) })),
              { sep: true, label: '' },
              { label: 'Step one window', icon: 'step', onClick: () => api.clock('step') },
              { label: 'Jump to a time…', icon: 'clock', onClick: () => setJump(true) },
              { label: ((c as any).skip_gaps ?? true) ? 'Stop skipping quiet stretches' : 'Skip quiet stretches', icon: 'chevron', onClick: () => api.clock('skip_gaps', ((c as any).skip_gaps ?? true) ? 0 : 1) },
            ]} />
            <div className="tb-progress">
              <div className="bar-track" style={{ height: 4 }}><div className="bar-fill" style={{ width: `${(c.progress ?? 0) * 100}%`, background: 'var(--accent)' }} /></div>
              <div className="row mono muted" style={{ justifyContent: 'space-between', fontSize: 10.5, marginTop: 3 }}>
                <span>{fmtDay(c.now, years)}{!years && ` ${fmtTime(c.now)}`}</span>
                <span>{catching ? `catching up ${Math.round(catching.progress * 100)}%` : c.done ? 'end' : c.paused ? 'paused' : 'playing'}</span>
              </div>
            </div>
            {jump && <JumpTo c={c} onClose={() => setJump(false)} />}
          </>
        ) : <span className="row mono" style={{ gap: 8 }}><span className="live-dot run" />live · {fmtTime(c.now)} UTC</span>}
      </div>
    </header>
  )
}

function JumpTo({ c, onClose }: { c: Snapshot['clock']; onClose: () => void }) {
  const [to, setTo] = useState((c.now ?? '').slice(0, 16))
  return (
    <form className="row jump" onSubmit={(e) => { e.preventDefault(); if (to) { api.clockJump(to); onClose() } }}>
      <input className="input" type="datetime-local" min={(c.start ?? '').slice(0, 16)} max={(c.end ?? '').slice(0, 16)} value={to} onChange={(e) => setTo(e.target.value)} style={{ width: 200, padding: '4px 8px' }} autoFocus />
      <button className="btn sm primary" type="submit">Go</button>
      <button className="btn sm ghost" type="button" onClick={onClose}><Icon name="x" size={12} /></button>
    </form>
  )
}

function LensDialog() {
  const open = useStore((x) => x.lensDialog)
  const [name, setName] = useState('')
  if (!open) return null
  const close = () => { useStore.setState({ lensDialog: false }); setName('') }
  return (
    <div className="modal-backdrop" onClick={close}>
      <div className="modal" style={{ width: 'min(460px, 100%)' }} onClick={(e) => e.stopPropagation()}>
        <form className="studio-body stack" onSubmit={async (e) => { e.preventDefault(); if (name.trim() && await lensAction('save', name.trim())) close() }}>
          <div className="label">Save as a lens</div>
          <div className="display" style={{ fontSize: 24, lineHeight: 1.2 }}>Name this layout</div>
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>A lens is a saved dashboard for a scenario. You can switch between lenses from the top bar; each keeps its own pages and history.</p>
          <input className="input" autoFocus placeholder="e.g. Incident review, Weekly report" value={name} onChange={(e) => setName(e.target.value)} />
          <div className="row" style={{ justifyContent: 'flex-end' }}>
            <button className="btn ghost" type="button" onClick={close}>Cancel</button>
            <button className="btn primary" type="submit" disabled={!name.trim()}>Save and switch</button>
          </div>
        </form>
      </div>
    </div>
  )
}
