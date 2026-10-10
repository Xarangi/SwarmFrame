import React, { useEffect, useMemo, useRef, useState } from 'react'
import { get, post } from '../api'
import { StudioTab, useStore } from '../store'
import type { DashState, PageSpec, PanelSpec, Snapshot, ViewData } from '../types'
import { Empty, fmtNum, Icon } from '../components/ui'
import { dashOps, Menu, MenuItem, undoLast } from '../components/kit'
import { PANELS, useCapabilities } from '../panels/panels'
import { ViewBody, ViewChart } from '../primitives/views'
import { Designer } from '../components/Appearance'

export { dashOps }

/* ================================================================== a page of panels */
export function CustomPage({ s, pageId }: { s: Snapshot; pageId: string }) {
  const dash = useStore((x) => x.dash)
  const [edit, setEdit] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const page = dash?.spec.pages.find((p) => p.id === pageId)
  useEffect(() => { setEdit(false); setRenaming(false) }, [pageId])
  useEffect(() => {
    if (dash && !page) { useStore.getState().setRoute('brief'); useStore.getState().showToast(`That page is not in the lens ${dash.lens}; back to the Brief`) }
  }, [dash, page]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!dash) return <div className="skeleton" style={{ height: 300 }} />
  if (!page) return <Empty title="This page no longer exists.">It may have been removed. Undo from the toast, or open History in Edit.</Empty>
  return (
    <div className="fade-in">
      <header className="page-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          {renaming
            ? <RenameForm page={page} onDone={() => setRenaming(false)} />
            : <h1 className="page-title">{page.title}</h1>}
          {page.description && <p className="page-sub">{page.description}</p>}
        </div>
        <PageEditMenu page={page} edit={edit} setEdit={setEdit} onRename={() => setRenaming(true)} />
      </header>
      <PageGrid s={s} page={page} edit={edit} />
      {!page.panels.length && (
        <div className="empty-page">
          <div className="serif">This page is empty.</div>
          <button className="btn" onClick={() => useStore.getState().setStudioOpen(true, 'add', page.id)}><Icon name="plus" size={14} />Add a panel</button>
        </div>
      )}
    </div>
  )
}

function RenameForm({ page, onDone }: { page: PageSpec; onDone: () => void }) {
  const [t, setT] = useState(page.title)
  const done = useRef(false)
  const commit = async (save: boolean) => {
    if (done.current) return
    done.current = true
    if (save && t.trim() && t.trim() !== page.title) await dashOps([{ op: 'update_page', page: page.id, title: t.trim() }], 'renamed a page', `Renamed to ${t.trim()}`)
    onDone()
  }
  return (
    <form className="row" onSubmit={(e) => { e.preventDefault(); commit(true) }}>
      <input className="input page-title-input" autoFocus value={t} onChange={(e) => setT(e.target.value)} onBlur={() => commit(true)}
        onKeyDown={(e) => { if (e.key === 'Escape') commit(false) }} aria-label="Page name (Enter to save, Esc to cancel)" />
    </form>
  )
}

/** Edit ▾: the same menu on every page, the Brief included. */
export function PageEditMenu({ page, edit, setEdit, onRename, extra = [] }: {
  page: PageSpec; edit: boolean; setEdit: (v: boolean) => void; onRename?: () => void; extra?: MenuItem[]
}) {
  const studio = useStore((x) => x.setStudioOpen)
  const llm = useStore((x) => x.snap?.org.llm_mode)
  const isBrief = page.id === 'brief'
  const pages = useStore((x) => x.dash?.spec.pages) ?? []
  const idx = pages.findIndex((p) => p.id === page.id)
  const siblings = pages.filter((p) => p.id !== 'brief' && p.nav === page.nav)
  const pos = siblings.findIndex((p) => p.id === page.id)
  const move = (d: -1 | 1) => {
    const other = siblings[pos + d]
    if (!other) return
    const to = pages.findIndex((p) => p.id === other.id)
    dashOps([{ op: 'move_page', page: page.id, to }], `moved ${page.id}`, d < 0 ? 'Moved up' : 'Moved down')
  }
  const hasDefault = isBrief || page.by === 'pack'
  void idx
  const items: MenuItem[] = [
    { label: 'Add a panel', icon: 'plus', hint: 'any built-in, or a view from another page', onClick: () => studio(true, 'add', page.id) },
    { label: 'Build a view', icon: 'evaluate', hint: 'pick a chart and a field', onClick: () => studio(true, 'build', page.id) },
    { label: 'Ask the designer', icon: 'spark', hint: llm === 'stub' ? 'plain requests, no model' : 'describe what you want', onClick: () => studio(true, 'ask', page.id) },
    { label: 'Change the look', icon: 'palette', hint: 'colours, typefaces, density', onClick: () => { localStorage.setItem('ss.settingsTab', 'appearance'); useStore.getState().setRoute('settings') } },
    { sep: true, label: '' },
    { label: edit ? 'Done arranging' : 'Arrange panels', icon: 'grip', hint: 'resize, reorder, remove', onClick: () => setEdit(!edit) },
    ...extra,
    ...(!isBrief && onRename ? [{ label: 'Rename page', icon: 'edit', onClick: onRename }] : []),
    ...(!isBrief ? [{ label: page.nav === 'top' ? 'Move under Activity' : 'Give it its own nav entry', icon: 'layers',
      onClick: () => dashOps([{ op: 'update_page', page: page.id, nav: page.nav === 'top' ? 'activity' : 'top' }], 'moved a page in the nav', 'Moved in the nav') }] : []),
    ...(!isBrief && siblings.length > 1 ? [
      { label: 'Move up in the nav', icon: 'arrow', disabled: pos <= 0, onClick: () => move(-1) },
      { label: 'Move down in the nav', icon: 'down', disabled: pos >= siblings.length - 1, onClick: () => move(1) }] : []),
    { sep: true, label: '' },
    { label: 'Save as a lens…', icon: 'lens', hint: 'a named layout for a scenario', onClick: () => useStore.setState({ lensDialog: true, drawer: null, studioOpen: false }) },
    { label: 'History and undo', icon: 'undo', onClick: () => studio(true, 'history', page.id) },
    { label: 'Reset this page', icon: 'clock', disabled: !hasDefault, hint: hasDefault ? "back to the source's default" : 'pages you made have no default; use Undo or History', onClick: () => dashOps([{ op: 'reset_page', page: page.id }], `reset ${page.id}`, `Reset ${page.title}`) },
    ...(!isBrief ? [{ label: 'Remove page', icon: 'x', danger: true, onClick: () => { dashOps([{ op: 'remove_page', page: page.id }], `removed page ${page.id}`, `Removed ${page.title}`); useStore.getState().setRoute('brief') } }] : []),
  ]
  return (
    <div className="row" style={{ gap: 8 }}>
      {edit && <button className="btn primary" onClick={() => setEdit(false)}><Icon name="check" size={14} />Done</button>}
      <Menu label="Edit" icon="edit" items={items} />
    </div>
  )
}

export function PageGrid({ s, page, edit }: { s: Snapshot; page: PageSpec; edit: boolean }) {
  const dash = useStore((x) => x.dash)!
  const caps = useCapabilities(s.source.id + s.source.synthetic)
  return (
    <div className="grid">
      {page.panels.map((p, i) => (
        <div key={p.id} className={`span-${Math.min(12, Math.max(3, p.span))}`}>
          <section className={`panel ${edit ? 'editing' : ''}`}>
            {edit && <PanelEditBar page={page} panel={p} index={i} />}
            <div className="panel-head">
              <span className="title">{p.title}</span>
              {p.kind === 'builtin' && !edit && PANELS.find((x) => x.id === p.builtin)?.kicker && (
                <span className="label kicker">{PANELS.find((x) => x.id === p.builtin)!.kicker!(s)}</span>)}
            </div>
            <div className="panel-body">
              {p.blurb && <div className="panel-blurb">{p.blurb}</div>}
              <PanelContent s={s} pageId={page.id} panel={p} version={dash.spec.version} caps={caps} />
            </div>
          </section>
        </div>
      ))}
    </div>
  )
}

function PanelContent({ s, pageId, panel, version, caps }: { s: Snapshot; pageId: string; panel: PanelSpec; version: number; caps: any }) {
  if (panel.kind === 'builtin') {
    const def = PANELS.find((x) => x.id === panel.builtin)
    if (!def) return <Empty title={`Unknown panel ${panel.builtin}`} />
    const missing = def.requires.filter((r) => (r === 'control' ? !s.control : !caps?.[r]?.present))
    if (caps && missing.length) return <Empty title="This source cannot show this panel.">It needs {missing.join(', ')}.</Empty>
    return <>{def.render(s)}</>
  }
  return <ViewBody page={pageId} panel={panel} version={version} />
}

function PanelEditBar({ page, panel, index }: { page: PageSpec; panel: PanelSpec; index: number }) {
  const W: [number, string][] = [[4, '⅓'], [6, '½'], [8, '⅔'], [12, 'full']]
  return (
    <div className="edit-bar">
      <div className="seg sm">
        {W.map(([n, l]) => (
          <button key={n} className={panel.span === n ? 'on' : ''} title={`${l} width`}
            onClick={() => dashOps([{ op: 'update_panel', page: page.id, panel_id: panel.id, changes: { span: n } }], `resized ${panel.id}`)}>{l}</button>
        ))}
      </div>
      <button className="btn sm ghost icon-sm" disabled={index === 0} title="Move earlier"
        onClick={() => dashOps([{ op: 'move_panel', page: page.id, panel_id: panel.id, to: index - 1 }], `moved ${panel.id}`)}>←</button>
      <button className="btn sm ghost icon-sm" disabled={index === page.panels.length - 1} title="Move later"
        onClick={() => dashOps([{ op: 'move_panel', page: page.id, panel_id: panel.id, to: index + 1 }], `moved ${panel.id}`)}>→</button>
      <button className="btn sm ghost icon-sm danger" title="Remove from this page"
        onClick={() => dashOps([{ op: 'remove_panel', page: page.id, panel_id: panel.id }], `removed ${panel.id}`, `Removed ${panel.title}`)}><Icon name="x" size={13} /></button>
    </div>
  )
}

/* ================================================================== the design studio */
interface Profile {
  source: { title: string; entity_noun: string; resource_noun: string; description: string }
  capabilities: Record<string, { present: boolean; quality: string; note: string }>
  time: { start: string | null; end: string | null; now: string; suggested_bucket: string; window_minutes: number }
  events: { total: number; visible_now: number; rate: [string, number][] }
  fields: Record<string, { distinct: number; top: [string, number][]; meaning: string }>
  attributes: Record<string, { type: string; distinct_in_sample?: number; usable_in_views: boolean; top_values: [string, number][] | null; note: string }>
  scale: Record<string, number | string>
}

const TABS: { id: StudioTab; label: string }[] = [
  { id: 'add', label: 'Add a panel' }, { id: 'build', label: 'Build a view' }, { id: 'ask', label: 'Ask the designer' }, { id: 'history', label: 'History' },
]

export function DesignStudio({ s }: { s: Snapshot }) {
  const open = useStore((x) => x.studioOpen)
  const tab = useStore((x) => x.studioTab)
  const pageId = useStore((x) => x.studioPage)
  const setOpen = useStore((x) => x.setStudioOpen)
  const dash = useStore((x) => x.dash)
  const [prof, setProf] = useState<Profile | null>(null)
  useEffect(() => { if (open && (tab === 'build' || tab === 'ask')) get<Profile>('/api/dashboard/profile').then(setProf).catch(() => setProf(null)) }, [open, tab, s.clock.index])
  useEffect(() => {
    if (!open) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [open, setOpen])
  if (!open || !dash) return null
  const target = dash.spec.pages.find((p) => p.id === pageId) ?? dash.spec.pages[0]
  return (
    <div className="modal-backdrop" onClick={() => setOpen(false)}>
      <div className="modal studio" onClick={(e) => e.stopPropagation()}>
        <div className="studio-head">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="label">Edit · {dash.lens} lens</div>
            <div className="display" style={{ fontSize: 26, lineHeight: 1.15 }}>
              {tab === 'history' ? 'History' : <>Change <PagePicker dash={dash} value={target.id} onChange={(id) => setOpen(true, tab, id)} /></>}
            </div>
          </div>
          <button className="btn ghost icon-btn" onClick={() => setOpen(false)} aria-label="Close"><Icon name="x" size={16} /></button>
        </div>
        <div className="studio-tabs">
          {TABS.map((t) => <button key={t.id} className={tab === t.id ? 'on' : ''} onClick={() => setOpen(true, t.id)}>{t.label}</button>)}
        </div>
        <div className="studio-body">
          {tab === 'add' && <Catalog s={s} dash={dash} page={target} />}
          {tab === 'build' && (prof ? <ViewBuilder dash={dash} prof={prof} page={target} /> : <div className="skeleton" style={{ height: 200 }} />)}
          {tab === 'ask' && <AskClaude s={s} dash={dash} page={target} prof={prof} />}
          {tab === 'history' && <History dash={dash} />}
        </div>
      </div>
    </div>
  )
}

function PagePicker({ dash, value, onChange }: { dash: DashState; value: string; onChange: (id: string) => void }) {
  return (
    <select className="inline-select" value={value} onChange={(e) => onChange(e.target.value)}>
      {dash.spec.pages.map((p) => <option key={p.id} value={p.id}>{p.id === 'brief' ? 'the Brief' : p.title}</option>)}
    </select>
  )
}

/* ------------------------------------------------------------------ add any panel to any page */
const GROUPS: { title: string; note: string; ids: string[] }[] = [
  { title: 'Overview', note: 'what SwarmFrame has found', ids: ['attention', 'brief', 'investigations', 'questions', 'executive', 'workstreams'] },
  { title: 'Activity', note: 'what the population is doing', ids: ['world', 'timeline', 'population', 'swimlane', 'say_do', 'lineage', 'environment', 'control', 'feed'] },
  { title: 'The machinery', note: 'how the oversight itself is working', ids: ['triage', 'cohorts', 'coverage', 'organization', 'health', 'monitor_attention', 'templates'] },
]

function Catalog({ s, dash, page }: { s: Snapshot; dash: DashState; page: PageSpec }) {
  const [q, setQ] = useState('')
  const here = new Set(page.panels.map((p) => (p.kind === 'builtin' ? `b:${p.builtin}` : `v:${p.id}`)))
  const match = (t: string) => !q || t.toLowerCase().includes(q.toLowerCase())
  const add = async (panel: Record<string, any>, title: string) => {
    const d = await dashOps([{ op: 'add_panel', page: page.id, panel }], `added ${title} to ${page.id}`, `Added ${title} to ${page.id === 'brief' ? 'the Brief' : page.title}`)
    if (d) { useStore.getState().setStudioOpen(false); useStore.getState().setRoute(page.id === 'brief' ? 'brief' : `page:${page.id}`) }
  }
  const views = dash.spec.pages.filter((p) => p.id !== page.id).flatMap((p) => p.panels.filter((x) => x.kind === 'view').map((x) => ({ p, x })))
  const uniq = (base: string) => { let id = base, n = 2; while (page.panels.some((x) => x.id === id)) id = `${base}_${n++}`; return id }
  return (
    <div className="stack" style={{ gap: 18 }}>
      <input className="input" placeholder="Find a panel…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 360 }} />
      {GROUPS.map((g) => {
        const defs = g.ids.map((id) => PANELS.find((p) => p.id === id)!).filter((d) => d && dash.builtins[d.id] !== undefined && match(d.title + d.blurb))
        if (!defs.length) return null
        return (
          <section key={g.title}>
            <div className="cat-head"><span className="h-section">{g.title}</span><span className="muted">{g.note}</span></div>
            <div className="cat-grid">
              {defs.map((d) => {
                const on = here.has(`b:${d.id}`)
                return (
                  <div key={d.id} className={`cat-card ${on ? 'on' : ''}`}>
                    <div className="cat-title">{d.title}</div>
                    <div className="cat-blurb">{d.blurb}</div>
                    <div className="cat-foot">
                      {on ? <span className="mono muted"><Icon name="check" size={12} /> on this page</span>
                        : <button className="btn sm" onClick={() => add({ id: uniq(d.id), title: d.title, builtin: d.id, span: d.span }, d.title)}><Icon name="plus" size={12} />Add</button>}
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        )
      })}
      {views.filter(({ x }) => match(x.title)).length > 0 && (
        <section>
          <div className="cat-head"><span className="h-section">Views on other pages</span><span className="muted">copy one here</span></div>
          <div className="cat-grid">
            {views.filter(({ x }) => match(x.title)).map(({ p, x }) => (
              <div key={p.id + x.id} className="cat-card">
                <div className="cat-title">{x.title}</div>
                <div className="cat-blurb">{x.view?.primitive} · on {p.id === 'brief' ? 'the Brief' : p.title}</div>
                <div className="cat-foot"><button className="btn sm" onClick={() => add({ ...x, id: uniq(x.id) }, x.title)}><Icon name="plus" size={12} />Add a copy</button></div>
              </div>
            ))}
          </div>
        </section>
      )}
      <div className="muted" style={{ fontSize: 12.5 }}>Not finding it? <button className="link" onClick={() => useStore.getState().setStudioOpen(true, 'build')}>Build a view</button> from any field of the stream.</div>
    </div>
  )
}

/* ------------------------------------------------------------------ ask Claude */
function AskClaude({ s, page, prof }: { s: Snapshot; dash: DashState; page: PageSpec; prof: Profile | null }) {
  const designing = useStore((x) => x.designing)
  const stub = s.org.llm_mode === 'stub'
  return (
    <div className="ask-grid">
      <div className="stack">
        <Designer scope="all" compact />
        <div className="card soft-card">
          The designer composes from a fixed library (numbers, trends, rankings, grids, tables, feeds, networks, two-sided
          maps, swimlanes, notes and the built-in panels) and a fixed set of look settings. It never writes code, every
          view is checked against the data before it is added, and every change can be undone from History.
          {stub && ' Without a model it understands plain look and layout requests; turn Claude on for new views.'}
        </div>
        <div className="row"><button className="btn" disabled={designing} onClick={() => post('/api/dashboard/design', { instruction: '', force: true }).then(() => useStore.getState().showToast(stub ? 'Recomposed with the free composer' : 'Recomposing; progress in the live column'))}>
          <Icon name="spark" size={14} />{designing ? 'Composing…' : `Recompose ${page.id === 'brief' ? 'the dashboard' : 'around this stream'}`}</button></div>
      </div>
      <ProfileView prof={prof} compact />
    </div>
  )
}

export function ProfileView({ prof, compact = false }: { prof: Profile | null; compact?: boolean }) {
  if (!prof) return <div className="card"><Empty title="Reading the stream…" /></div>
  const caps = Object.entries(prof.capabilities)
  const max = Math.max(1, ...prof.events.rate.map((r) => r[1]))
  const has = caps.filter(([, c]) => c.present), lacks = caps.filter(([, c]) => !c.present)
  return (
    <div className="card profile" style={{ maxHeight: compact ? 420 : '68vh' }}>
      <div className="label">What Claude sees (structure only, never agent text)</div>
      <div style={{ fontWeight: 600, marginTop: 4 }}>{prof.source.title}</div>
      <div className="mono muted" style={{ marginTop: 2 }}>{fmtNum(prof.events.visible_now)} of {fmtNum(prof.events.total)} events visible · {prof.source.entity_noun}s act on {prof.source.resource_noun}s</div>
      <div className="row" style={{ alignItems: 'flex-end', gap: 1, height: 34, marginTop: 10 }}>
        {prof.events.rate.map(([t, n]) => <div key={t} title={`${t}: ${n}`} style={{ flex: 1, height: `${Math.max(2, (n / max) * 100)}%`, background: 'var(--data)', opacity: 0.75, borderRadius: 1 }} />)}
      </div>
      <div className="label" style={{ marginTop: 14 }}>The stream has</div>
      <div className="row" style={{ flexWrap: 'wrap', gap: 5, marginTop: 6 }}>
        {has.map(([k, c]) => <span key={k} title={c.note} className="chip soft" style={{ color: 'var(--st-observed)' }}>{k.replace('_', ' ')}</span>)}
      </div>
      {lacks.length > 0 && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Not in this stream: {lacks.map(([k]) => k.replace('_', ' ')).join(', ')}. Views that need them are hidden.</div>}
      {!compact && <>
        <div className="label" style={{ marginTop: 14 }}>Fields</div>
        {Object.entries(prof.fields).filter(([, f]) => f.distinct).map(([k, f]) => (
          <div key={k} style={{ marginTop: 6 }}>
            <div className="row mono" style={{ justifyContent: 'space-between' }}><span>{k}</span><span className="muted">{fmtNum(f.distinct)} distinct</span></div>
            <div className="mono muted" style={{ fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{f.top.slice(0, 5).map(([v, n]) => `${v} (${fmtNum(n)})`).join(' · ')}</div>
          </div>
        ))}
        {Object.keys(prof.attributes).length > 0 && <div className="label" style={{ marginTop: 14 }}>Attributes</div>}
        {Object.entries(prof.attributes).map(([k, a]) => (
          <div key={k} className="row mono" style={{ justifyContent: 'space-between', marginTop: 4, fontSize: 11.5 }}>
            <span style={{ color: a.usable_in_views ? undefined : 'var(--ink-4)' }}>{k}</span>
            <span className="muted" style={{ textAlign: 'right' }}>{a.usable_in_views ? (a.top_values ?? []).slice(0, 3).map(([v]) => v).join(', ') || a.note : 'hidden: ' + a.note.split(':')[0]}</span>
          </div>
        ))}
      </>}
    </div>
  )
}

/* ------------------------------------------------------------------ history */
function History({ dash }: { dash: DashState }) {
  return (
    <div className="stack">
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <span className="mono muted">Version {dash.spec.version} · last change by {dash.spec.by}</span>
        <span style={{ flex: 1 }} />
        <button className="btn sm" onClick={() => dashOps([{ op: 'restore_builtin' }], 'restored default pages', "Restored the source's default pages")}>Restore default pages</button>
        <button className="btn sm" disabled={!dash.history.length} onClick={undoLast}><Icon name="undo" size={13} />Undo last change</button>
      </div>
      {dash.spec.rationale && <div className="card soft-card">{dash.spec.rationale}</div>}
      <div className="timeline-list">
        {[...dash.history].reverse().map((h) => (
          <div key={h.version} className="tl-item">
            <span className="mono muted">v{h.version}</span>
            <span className="chip soft" style={{ color: h.by === 'human' ? 'var(--st-derived)' : 'var(--accent)' }}>{h.by === 'human' ? 'you' : h.by}</span>
            <span style={{ fontSize: 13 }}>{h.rationale || '—'}</span>
          </div>
        ))}
        {!dash.history.length && <div className="muted">No changes yet.</div>}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ build a view by hand, with a real preview */
const PRIM_LABEL: Record<string, string> = { stat: 'A number', timeseries: 'Over time', bar: 'Ranking', heatmap: 'Grid (two fields)', table: 'Table', feed: 'Latest records', graph: 'Who works with whom', bipartite: 'Two-sided map', swimlane: 'Lanes over time' }
const FIELD_LABEL: Record<string, string> = { actor: 'who (agent)', object: 'where (resource)', family: 'workstream', action: 'action', group: 'team / group' }
const fieldName = (d: string) => FIELD_LABEL[d] ?? (d.startsWith('attr.') ? d.slice(5).replace('_', ' ') : d.startsWith('ts:') ? `time (${d.slice(3)})` : d)

function ViewBuilder({ dash, prof, page }: { dash: DashState; prof: Profile; page: PageSpec }) {
  const dims = useMemo(() => {
    const out = ['object', 'family', 'action']
    if (prof.capabilities.identities?.present) out.unshift('actor')
    if (prof.fields.group?.distinct) out.push('group')
    Object.entries(prof.attributes).filter(([, a]) => a.usable_in_views).forEach(([k]) => out.push(`attr.${k}`))
    return out
  }, [prof])
  const bucket = prof.time.suggested_bucket
  const [prim, setPrim] = useState('timeseries')
  const [dim, setDim] = useState('family')
  const [dim2, setDim2] = useState(bucket)
  const [metric, setMetric] = useState('count')
  const [hours, setHours] = useState('all')
  const [title, setTitle] = useState('')
  const [preview, setPreview] = useState<(ViewData & { ok: boolean; error?: string }) | null>(null)
  const query = (): Record<string, any> => {
    const time = hours === 'all' ? { all: true } : { last_hours: Number(hours) }
    const m = metric === 'count' ? {} : { metric }
    if (prim === 'stat') return { time, ...m }
    if (prim === 'timeseries') return { group_by: [bucket, dim], time, ...m }
    if (prim === 'heatmap') return { group_by: [dim, dim2], time, top: 20, ...m }
    if (prim === 'feed') return { time, top: 25 }
    if (prim === 'graph' || prim === 'bipartite') return { group_by: [dim, dim2.startsWith('ts:') ? (dim === 'object' ? 'actor' : 'object') : dim2], time, top: 40, ...m }
    if (prim === 'swimlane') return { group_by: [dim, bucket], time, top: 16, ...m }
    return { group_by: [dim], time, top: 15, ...m }
  }
  const view = () => ({ primitive: prim, query: query(), options: {} })
  const plural = (d: string) => ({ actor: `${prof.source.entity_noun}s`, object: `${prof.source.resource_noun}s`, family: 'workstreams', group: 'teams', action: 'actions' } as Record<string, string>)[d]
    ?? (d.startsWith('ts:') ? d.slice(3) + 's' : fieldName(d))
  const what = metric === 'count' ? 'Events' : metric === 'distinct:actor' ? `${prof.source.entity_noun}s` : `${prof.source.resource_noun}s`
  const autoTitle = () => title || (prim === 'stat' ? what : prim === 'feed' ? 'Latest records' : prim === 'graph' ? `${plural(dim)} that share ${plural(dim2.startsWith('ts:') ? 'object' : dim2)}` : prim === 'swimlane' ? `${plural(dim)} over time` : prim === 'timeseries' ? `${what} by ${fieldName(dim)}` : prim === 'heatmap' || prim === 'bipartite' ? `${plural(dim)} by ${plural(dim2)}` : `Busiest ${plural(dim)}`).replace(/^./, (c) => c.toUpperCase())
  useEffect(() => {
    let live = true
    const t = setTimeout(() => post('/api/dashboard/preview', { view: view() }).then((d) => { if (live) setPreview(d) }).catch(() => {}), 150)
    return () => { live = false; clearTimeout(t) }
  }, [prim, dim, dim2, hours, metric]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="builder">
      <div className="stack" style={{ gap: 14 }}>
        <div>
          <div className="label" style={{ marginBottom: 6 }}>Show it as</div>
          <div className="seg wrap">{Object.keys(PRIM_LABEL).filter((p) => dash.primitives[p]).map((p) => <button key={p} className={prim === p ? 'on' : ''} onClick={() => setPrim(p)}>{PRIM_LABEL[p]}</button>)}</div>
        </div>
        {prim !== 'stat' && prim !== 'feed' && (
          <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
            <label className="field"><span className="label">{prim === 'timeseries' ? 'Split by' : prim === 'heatmap' ? 'Rows' : prim === 'graph' ? 'Nodes' : prim === 'bipartite' ? 'Left side' : prim === 'swimlane' ? 'One lane per' : 'Rank'}</span>
              <select className="input" value={dim} onChange={(e) => setDim(e.target.value)}>{dims.map((d) => <option key={d} value={d}>{fieldName(d)}</option>)}</select></label>
            {(prim === 'heatmap' || prim === 'graph' || prim === 'bipartite') && <label className="field"><span className="label">{prim === 'graph' ? 'Linked through' : prim === 'bipartite' ? 'Right side' : 'Columns'}</span>
              <select className="input" value={dim2} onChange={(e) => setDim2(e.target.value)}>{[bucket, ...dims].map((d) => <option key={d} value={d}>{fieldName(d)}</option>)}</select></label>}
          </div>
        )}
        <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <label className="field"><span className="label">Count</span>
            <select className="input" value={metric} onChange={(e) => setMetric(e.target.value)}>
              <option value="count">events</option>
              {prof.capabilities.identities?.present && <option value="distinct:actor">distinct {prof.source.entity_noun}s</option>}
              <option value="distinct:object">distinct {prof.source.resource_noun}s</option>
            </select></label>
          <label className="field"><span className="label">Over</span>
            <select className="input" value={hours} onChange={(e) => setHours(e.target.value)}>
              <option value="all">all time so far</option><option value="6">last 6 hours</option><option value="24">last 24 hours</option><option value="168">last 7 days</option><option value="720">last 30 days</option>
            </select></label>
        </div>
        <label className="field"><span className="label">Title</span><input className="input" placeholder={autoTitle()} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
        <div className="row">
          <button className="btn primary" onClick={async () => {
            const panel = { title: autoTitle(), span: prim === 'stat' ? 4 : ['heatmap', 'timeseries', 'graph', 'bipartite', 'swimlane'].includes(prim) ? 8 : 6, view: view() }
            const d = await dashOps([{ op: 'add_panel', page: page.id, panel }], `added ${panel.title}`, `Added ${panel.title} to ${page.id === 'brief' ? 'the Brief' : page.title}`)
            if (d) { useStore.getState().setStudioOpen(false); useStore.getState().setRoute(page.id === 'brief' ? 'brief' : `page:${page.id}`) }
          }}><Icon name="plus" size={14} />Add to {page.id === 'brief' ? 'the Brief' : page.title}</button>
        </div>
      </div>
      <div className="preview">
        <div className="label" style={{ marginBottom: 8 }}>Preview · {autoTitle()}</div>
        {!preview ? <div className="skeleton" style={{ height: 160 }} />
          : preview.ok ? <ViewChart primitive={prim} data={preview} />
            : <div className="mono" style={{ color: 'var(--st-contradicted)' }}>{preview.error}</div>}
      </div>
    </div>
  )
}
