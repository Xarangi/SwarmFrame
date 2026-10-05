import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api, get, post } from '../api'
import { useStore } from '../store'
import type { Snapshot } from '../types'
import { Empty, fmtNum, Icon } from '../components/ui'
import { Menu, Tip, useTerms } from '../components/kit'
import * as THREE from 'three'
import { STATES, WorldView, WSpec, WState } from '../world/view'
import { buildGroup, MDef } from '../world/models'
import { behaviourCounts, zoneSwatch } from '../world/scene'

/* What the server sends with the spec */
interface Binding { channel: string; quantity: string; status: string; legend: string }
interface Scene { id: string; title: string; camera: string; target: string | null; question: string; finding_kind: string | null; opening: boolean }
interface FullSpec extends WSpec {
  version: number; by: string; rationale: string; metric: { sentence: string; forces: Record<string, number>; interactions: string[] }
  bindings: Binding[]; scenes: Scene[]; unavailable: string[]; reasons: Record<string, string>; open_questions: string[]
  annotations: { id: string; at: string; text: string; by: string }[]
  landmarks?: { label: string; archetype: string; model?: string | null }[]
}
interface SpecResp { spec: FullSpec; history: { version: number; by: string; rationale: string }[]; designing: boolean }

const STATUS_WORD: Record<string, string> = { observed: 'observed', derived: 'derived', inferred: 'inferred' }

/** The World as a full page: the swarm in 3D, where position is a measurement. */
export function World({ s }: { s: Snapshot }) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<WorldView | null>(null)
  const [spec, setSpec] = useState<SpecResp | null>(null)
  const [st, setSt] = useState<WState | null>(null)
  const [hover, setHover] = useState<{ kind: string; id: string; x: number; y: number } | null>(null)
  const [card, setCard] = useState<{ kind: 'unit' | 'landmark'; id: string } | null>(null)
  const [sel, setSel] = useState<string[]>([])
  const [legend, setLegend] = useState(() => { const v = localStorage.getItem('ss.worldLegend'); return v === null ? window.innerWidth > 1500 : v !== '0' })
  const [scene, setScene] = useState<string | null>(null)
  const tick = useStore((x) => x.tick)
  const focus = useStore((x) => x.worldFocus)

  useEffect(() => {
    if (!host.current) return
    const v = new WorldView(host.current, {
      onHover: (u, x, y) => setHover(u ? { kind: u.kind, id: u.id, x, y } : null),
      onClick: (u) => setCard(u ? { kind: u.kind, id: u.id } : null),
      onSelect: (ids) => setSel(ids),
    })
    view.current = v
    return () => { v.dispose(); view.current = null }
  }, [])
  // spec: on mount and whenever the server says the World changed
  const wver = s.world?.version
  const [bump, setBump] = useState(0)
  useEffect(() => { const on = () => setBump((b) => b + 1); window.addEventListener('world-spec', on); return () => window.removeEventListener('world-spec', on) }, [])
  useEffect(() => { const v = view.current; if (v) { v.insetRight = legend && window.innerWidth > 760 ? 316 : 0; if (st) v.overview() } }, [legend]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { get<SpecResp>('/api/world/spec').then((d) => { setSpec(d); view.current?.setSpec(d.spec) }).catch(() => {}) }, [wver, bump])
  // state: every snapshot (once per window)
  const idsVer = useRef(-1)
  useEffect(() => {
    let live = true
    const withLabels = idsVer.current < 0 || (st?.ids_version ?? -1) !== idsVer.current
    get<WState>(`/api/world/state?ids=1${withLabels ? '&labels=1' : ''}`).then((d) => {
      if (!live || d.empty) return
      if (withLabels) idsVer.current = d.ids_version
      setSt(d); view.current?.setState(d)
    }).catch(() => {})
    return () => { live = false }
  }, [s.world?.window ?? tick]) // eslint-disable-line react-hooks/exhaustive-deps
  // "Show me" from a finding, or a link from elsewhere
  useEffect(() => {
    if (!focus || !st || !view.current) return
    const kind = focus.split(':')[0]
    const id = focus.slice(kind.length + 1)
    const v = view.current
    const ok = kind === 'agent' || kind === 'actor' ? v.focusUnit(id) : kind === 'resource' ? (v.focusLandmark(id) || v.focusUnit(id))
      : kind === 'cohort' ? v.focusSet(v.ids.filter((_, i) => st.cohort_ids[v.coh[i]] === id)) : false
    if (ok && (kind === 'agent' || kind === 'actor')) setCard({ kind: 'unit', id })
    if (ok && kind === 'resource') setCard({ kind: 'landmark', id })
    if (!ok) {
      v.overview()
      useStore.getState().showToast(kind === 'artifact' ? 'Reused content has no single place in the World; the purple arcs show where it travelled'
        : kind === 'family' || kind === 'population' ? 'This finding is about the whole population: showing the overview'
          : 'This finding is not on the map right now (quiet, or outside the recent windows)')
    }
    useStore.setState({ worldFocus: null })
  }, [focus, st])

  const scenes = spec?.spec.scenes ?? []
  const runScene = (sc: Scene) => {
    const v = view.current
    if (!v || !st) return
    setScene(sc.id)
    const f = st.flags || {}
    if (sc.camera === 'overview' || sc.camera === 'sweep') { setCard(null); return v.overview() }
    if (sc.camera === 'follow') { const u = card?.kind === 'unit' ? card.id : v.ids[0]; if (u) { v.focusUnit(u, true); setCard({ kind: 'unit', id: u }) } return }
    const t = sc.target ?? ''
    const none = (msg: string) => { setCard(null); v.overview(); useStore.getState().showToast(msg) }
    if (t === 'crowding') {
      const lm = f.crowding?.[0] ?? [...st.landmarks].sort((a, b) => b.crowding - a.crowding)[0]?.id
      if (!f.crowding?.length) useStore.getState().showToast('No place is more crowded than chance right now; showing the busiest one')
      if (lm) { v.focusLandmark(lm); setCard({ kind: 'landmark', id: lm }) }
      return
    }
    if (t === 'drift' || t === 'isolation') { const u = f[t]?.[0]; if (u) { v.focusUnit(u); setCard({ kind: 'unit', id: u }) } else none(t === 'drift' ? 'No one is drifting beyond chance right now' : 'No one stands apart beyond chance right now'); return }
    if (t === 'still_talking') { if (!v.focusSet(f.still_talking ?? [])) none('No one is talking without moving right now'); else setCard(null); return }
    if (t === 'beams') { const ids = st.relations.filter((r) => r.t === 'beam').map((r) => v.ids[r.a]); if (!v.focusSet(ids)) none('No operator actions in this window'); else setCard(null); return }
    if (t === 'blocked') { const ids = v.ids.filter((_, i) => v.state[i] === 4 || v.state[i] === 5); if (!v.focusSet(ids)) none('No one is blocked or waiting right now'); else setCard(null); return }
    if (t === 'activity') { let best = 0; for (let i = 1; i < v.ids.length; i++) if (v.h[i] > v.h[best]) best = i; v.focusUnit(v.ids[best]); setCard({ kind: 'unit', id: v.ids[best] }); return }
    if (t === 'new_roads') { const lm = st.landmarks.find((l) => l.new) ?? st.landmarks[0]; if (lm) v.focusLandmark(lm.id); return }
    v.overview()
  }

  const flags = st?.flags ?? {}
  const showSet = (ids: string[]) => { const v = view.current; if (!v) return; if (ids.length === 1) { v.focusUnit(ids[0]); setCard({ kind: 'unit', id: ids[0] }) } else { v.focusSet(ids); setCard(null) } }
  const chips: [string, string, () => void][] = [
    ...((flags.drift?.length ?? 0) ? [[`${flags.drift.length} drifting`, 'Moved further than any agent in a shuffled swarm usually does', () => showSet(flags.drift)] as [string, string, () => void]] : []),
    ...((flags.crowding?.length ?? 0) ? [[`${flags.crowding.length} crowded place${flags.crowding.length > 1 ? 's' : ''}`, 'More units than usual on one place', () => { view.current?.focusLandmark(flags.crowding[0]); setCard({ kind: 'landmark', id: flags.crowding[0] }) }] as [string, string, () => void]] : []),
    ...((flags.split?.length ?? 0) ? [[`${flags.split.length} group${flags.split.length > 1 ? 's' : ''} coming apart`, 'A group whose spread jumped', () => { const c = flags.split[0]; const v = view.current; if (v && st) { v.focusSet(v.ids.filter((_, i) => st.cohort_ids[v.coh[i]] === c)); setCard(null) } }] as [string, string, () => void]] : []),
    ...((flags.still_talking?.length ?? 0) ? [[`${flags.still_talking.length} talking, not moving`, 'Sending messages without doing anything new', () => showSet(flags.still_talking)] as [string, string, () => void]] : []),
  ]

  return (
    <div className="world-page fade-in">
      <header className="world-head">
        <div style={{ minWidth: 0, flex: '1 1 380px' }}>
          <div className="row" style={{ gap: 10, alignItems: 'baseline' }}>
            <h1 className="page-title">World</h1>
            {spec && <span className="label">{spec.spec.shape.replace('_', ' ')} · {st ? `${fmtNum(st.n)} on the map` : 'loading'} · {spec.spec.render.tier && spec.spec.render.tier !== 'auto' ? `drawn as ${spec.spec.render.tier}` : (st?.tier ?? '')}</span>}
          </div>
          <p className="page-sub world-metric">{spec?.spec.metric.sentence ?? 'Where a unit stands is a measurement.'}</p>
        </div>
        {scenes.length > 0 && (
          <div className="seg scenes">
            {scenes.map((sc) => <Tip key={sc.id} text={sc.question}><button className={scene === sc.id || (!scene && sc.opening) ? 'on' : ''} onClick={() => runScene(sc)}>{sc.title}</button></Tip>)}
          </div>
        )}
        <div className="world-actions">
          <button className={`btn ${legend ? 'pressed' : ''}`} onClick={() => { setLegend(!legend); localStorage.setItem('ss.worldLegend', legend ? '0' : '1') }}><Icon name="layers" size={14} />Legend</button>
          <WorldEditMenu s={s} spec={spec} />
        </div>
      </header>
      <div className="world-stage" ref={host}>
        {!st && <div className="world-empty"><Empty title={s.population.total_events_seen ? 'Laying out the world…' : 'The World fills in as events arrive.'}>Each window, units move toward the places they use and the units they work with.</Empty></div>}
        {chips.length > 0 && (
          <div className="world-chips">
            {chips.map(([t, h, go]) => <Tip key={t} text={h}><button className="world-chip" onClick={go}><span className="dot" />{t}</button></Tip>)}
          </div>
        )}
        {legend && spec && <Legend spec={spec.spec} st={st} />}
        {hover && st && <HoverTip h={hover} st={st} view={view.current} />}
        {card && <Card c={card} spec={spec?.spec} onClose={() => setCard(null)} view={view.current} onFollow={(id) => view.current?.focusUnit(id, true)} />}
        {sel.length > 0 && <SelectionBar ids={sel} onClear={() => setSel([])} view={view.current} />}
        <div className="world-hint">drag to orbit · scroll to zoom · right-drag to pan · shift-drag to select</div>
      </div>
    </div>
  )
}

function WorldEditMenu({ s, spec }: { s: Snapshot; spec: SpecResp | null }) {
  const stub = s.org.llm_mode === 'stub'
  const show = useStore((x) => x.showToast)
  const [models, setModels] = useState(false)
  const made = spec?.spec.models ?? []
  const design = async (instruction = '') => {
    try { await post('/api/world/design', { instruction }); show(stub ? 'Recomposed with the free composer' : 'The world-designer is working; progress appears in the chat') } catch (e: any) { show(String(e.message || e)) }
  }
  const ops = async (ops: Record<string, any>[], msg: string) => {
    try { await post('/api/world/ops', { ops }); show(msg, true); window.dispatchEvent(new Event('world-spec')) } catch (e: any) { show(String(e.message || e).replace(/^\d+ /, '')) }
  }
  const tier = spec?.spec.render.tier ?? 'auto'
  return (
    <>
    <Menu label="Edit" icon="edit" items={[
      { label: stub ? 'Recompose (free)' : 'Ask Claude to redesign', icon: 'spark', hint: stub ? 'fixed rules from what this stream can show' : 'one world-designer session; models are on', onClick: () => design() },
      { label: 'Ask Claude about this World', icon: 'chat', hint: 'opens the copilot', onClick: () => useStore.getState().askCopilot('Looking at the World: what stands out right now, and is any of it beyond what a shuffled swarm would show?') },
      { label: 'Ask Claude for a new 3D model…', icon: 'plus', hint: 'when no premade character or place fits this stream', onClick: () => useStore.getState().askCopilot('In the World, make a 3D model for ') },
      { label: `Models made for this stream${made.length ? ` (${made.length})` : ''}`, icon: 'layers', disabled: !made.length, hint: made.length ? 'see them turn, read what each stands for' : 'none yet: the premade library is in use', onClick: () => setModels(true) },
      { sep: true, label: '' },
      ...(['auto', 'characters', 'pawns', 'dots'] as const).map((t) => ({ label: `Draw units as ${t}`, icon: tier === t ? 'check' : undefined, hint: t === 'auto' ? 'by population and zoom' : t === 'characters' ? 'only sensible below ~80 units' : t === 'pawns' ? 'up to ~2,000 units' : 'thousands of units',
        onClick: () => ops([{ op: 'set_render', tier: t }], `Units drawn as ${t}`) })),
      { label: spec?.spec.coverage_fog ? 'Hide coverage fog' : 'Show coverage fog', icon: 'eye', onClick: () => ops([{ op: 'set_fog', on: !spec?.spec.coverage_fog }], spec?.spec.coverage_fog ? 'Coverage fog hidden' : 'Coverage fog shown') },
      { sep: true, label: '' },
      { label: 'Undo last World change', icon: 'undo', disabled: !spec?.history.length, onClick: async () => { try { await post('/api/world/undo'); show('Undone'); window.dispatchEvent(new Event('world-spec')) } catch { show('Nothing to undo') } } },
      { label: "Reset to the source's world", icon: 'clock', onClick: () => ops([{ op: 'reset_world' }], 'World reset') },
    ]} />
    {models && spec && <ModelsModal spec={spec.spec} onClose={() => setModels(false)} onRemove={(id) => ops([{ op: 'remove_model', id }], `Removed ${id}`)} />}
    </>
  )
}

/** the models Claude made for this stream: a turntable preview, what each stands for, and where it is used */
function ModelsModal({ spec, onClose, onRemove }: { spec: FullSpec; onClose: () => void; onRemove: (id: string) => void }) {
  const models = spec.models ?? []
  const [pick, setPick] = useState(models[0]?.id ?? '')
  const def = models.find((m) => m.id === pick) ?? models[0]
  const host = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!host.current || !def) return
    const el = host.current
    const night = (() => { const c = new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#f4efe6'); return c.getHSL({ h: 0, s: 0, l: 0 }).l < 0.3 })()
    const r = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    r.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    r.setSize(el.clientWidth, el.clientHeight)
    el.appendChild(r.domElement)
    const scene = new THREE.Scene()
    scene.add(new THREE.HemisphereLight(0xffffff, night ? 0x202020 : 0xd8cfc0, night ? 0.8 : 1.2))
    const sun = new THREE.DirectionalLight(0xffffff, night ? 0.9 : 1.5); sun.position.set(3, 6, 4); scene.add(sun)
    const tint = getComputedStyle(document.documentElement).getPropertyValue('--c2').trim() || '#3f7fbf'
    const b = buildGroup(def, night, tint)
    const box = new THREE.Box3().setFromObject(b.group)
    const size = box.getSize(new THREE.Vector3()), mid = box.getCenter(new THREE.Vector3())
    const R = Math.max(size.x, size.y, size.z, 0.5)
    const floor = new THREE.Mesh(new THREE.CircleGeometry(R * 0.9, 40).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ color: night ? 0x2b2925 : 0xece6dc, roughness: 1 }))
    scene.add(floor, b.group)
    const cam = new THREE.PerspectiveCamera(35, el.clientWidth / el.clientHeight, 0.01, 100)
    let raf = 0
    const loop = (t: number) => {
      const a = t / 2600
      cam.position.set(mid.x + Math.sin(a) * R * 2.4, mid.y + R * 0.9, mid.z + Math.cos(a) * R * 2.4)
      cam.lookAt(mid)
      b.animate(t / 1000)
      r.render(scene, cam)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => { cancelAnimationFrame(raf); b.dispose(); floor.geometry.dispose(); (floor.material as THREE.Material).dispose(); r.dispose(); r.domElement.remove() }
  }, [def?.id, JSON.stringify(def?.parts)]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!def) return null
  const uses = [
    ...(spec.landmarks ?? []).filter((l) => l.model === def.id).map((l) => `places: ${l.label}`),
    ...((spec.render.character === def.id && (spec.render.character_by === 'fixed' || spec.render.character_by === 'none')) || (spec.render.cast ?? []).includes(def.id) ? ['agents (characters tier)'] : []),
    ...(spec.scenery ?? []).filter((x) => x.model === def.id).map((x) => `scenery: ${x.at}`),
  ]
  const KIND: Record<string, string> = { landmark: 'a place', unit: 'an agent character', prop: 'scenery (encodes nothing)' }
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 'min(760px, 100%)' }} onClick={(e) => e.stopPropagation()}>
        <div className="studio-head"><div style={{ flex: 1 }}><div className="label">The World</div><div className="display" style={{ fontSize: 24 }}>Models made for this stream</div></div>
          <button className="btn ghost icon-btn" onClick={onClose}><Icon name="x" size={16} /></button></div>
        <div className="studio-body models-body">
          <div className="models-list">
            {models.map((m) => (
              <button key={m.id} className={`models-item ${m.id === def.id ? 'on' : ''}`} onClick={() => setPick(m.id)}>
                <span className="mono">{m.id}</span><span className="muted">{KIND[m.kind] ?? m.kind}</span>
              </button>
            ))}
          </div>
          <div className="stack" style={{ gap: 10, minWidth: 0 }}>
            <div className="models-stage" ref={host} />
            <div style={{ fontSize: 14 }}>{def.meaning}</div>
            <div className="muted" style={{ fontSize: 12.5 }}>{def.parts.length} parts · by {def.by ?? 'designer'} · {uses.length ? `used for ${uses.join(', ')}` : 'not used yet'}</div>
            <div className="row" style={{ gap: 8 }}>
              <button className="btn sm" onClick={() => useStore.getState().askCopilot(`In the World, change the model ${def.id}: `)}><Icon name="chat" size={13} />Ask Claude to change it</button>
              <button className="btn sm ghost" onClick={() => onRemove(def.id)}><Icon name="x" size={13} />Remove</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function Legend({ spec, st }: { spec: FullSpec; st: WState | null }) {
  const terms = useTerms()
  const groups: [string, string[]][] = [['Where things are', ['position', 'trail']], ['How they look', ['height', 'colour', 'state', 'alpha', 'material', 'bubble', 'banner', 'ring']], ['The ground and places', ['heat', 'fog', 'territory', 'size']]]
  const by = Object.fromEntries(spec.bindings.map((b) => [b.channel, b]))
  const rel: Record<string, string> = { arc_touch: 'Thin arcs: acted on the same place this window.', arc_reply: 'Blue arcs: one answered the other.', arc_lineage: 'Purple arcs: content one posted and the other reused (dashed: we did not see how it got there).', beam: 'Beams from above: an operator stopped (red), paused or denied (amber), or messaged (grey) this unit.' }
  return (
    <aside className="world-legend">
      <SceneLegend spec={spec} st={st} />
      {groups.map(([title, chans]) => {
        const rows = chans.map((c) => by[c]).filter(Boolean)
        if (!rows.length) return null
        return (
          <section key={title}>
            <div className="label">{title}</div>
            {rows.map((b) => (
              <div key={b.channel} className={`lg-row ${b.status}`}>
                <span className="lg-text">{b.legend}</span>
                {b.status !== 'derived' && <span className={`lg-status ${b.status}`}>{STATUS_WORD[b.status] ?? b.status}</span>}
              </div>
            ))}
          </section>
        )
      })}
      {spec.relations.length > 0 && <section><div className="label">Lines</div>{spec.relations.map((r) => <div key={r} className="lg-row"><span className="lg-text">{rel[r]}</span></div>)}</section>}
      {!st?.catalog && <section>
        <div className="label">Glow</div>
        <div className="lg-row"><span className="lg-text">A thin blue pillar marks a {terms.agent} that moved or stands apart more than any {terms.agent} in a shuffled swarm usually does{st?.null.drift != null ? ` (threshold ${st.null.drift.toFixed(3)})` : ''}.</span></div>
      </section>}
      {((spec.models ?? []).length > 0 || (spec.scenery ?? []).length > 0) && (
        <section><div className="label">Made for this stream</div>
          {(spec.models ?? []).filter((m) => m.kind !== 'prop').map((m) => <div key={m.id} className="lg-row"><span className="lg-text">{m.meaning}</span><span className="lg-status made">{m.kind === 'unit' ? 'agent' : 'place'}</span></div>)}
          {(spec.scenery ?? []).map((x, i) => <div key={i} className="lg-row muted"><span className="lg-text">Scenery: {x.meaning}</span></div>)}
        </section>
      )}
      {spec.unavailable?.length > 0 && (
        <section><div className="label">Not in this stream</div>
          {spec.unavailable.slice(0, 6).map((u) => <div key={u} className="lg-row muted"><span className="lg-text">{u.split(':')[0]}</span></div>)}
        </section>
      )}
    </aside>
  )
}

/** "What you are seeing": the scene the stream lives in, and what each unit does this window (its activity rules) */
function SceneLegend({ spec, st }: { spec: FullSpec; st: WState | null }) {
  const sl = spec.scene_legend
  const beh = spec.behaviours ?? []
  const counts = useMemo(() => behaviourCounts(st?.acts, beh.length), [st?.acts, beh.length])
  if (!sl || (!beh.length && !sl.zones.length && !sl.props.length)) return null
  const tierStill = st?.tier === 'dots'
  return (
    <section className="lg-scene">
      <div className="label">What you are seeing</div>
      {beh.length > 0 && <>
        {beh.map((b, i) => (
          <div key={b.id || i} className="lg-row"><span className="lg-text">{b.meaning}</span>{st && counts[i] > 0 && <span className="lg-count">{fmtNum(counts[i])} now</span>}</div>
        ))}
        <div className="lg-row muted"><span className="lg-text">{tierStill ? 'From afar units stay put; zoom in to see them move. ' : ''}Every trip ends where the measurements put the unit; the first rule that fits decides what it does.</span></div>
      </>}
      {sl.zones.length > 0 && (
        <div className="lg-zones">
          {sl.zones.map((z) => <span key={z.name} className="lg-zone"><i style={{ background: zoneSwatch(z.style) }} />{z.label}</span>)}
        </div>
      )}
      <div className="lg-row muted"><span className="lg-text">Ground: {sl.ground}.{sl.props.length ? ` Scenery (${sl.props.slice(0, 5).join(', ')}${sl.props.length > 5 ? ', …' : ''}) only sets the scene: it encodes nothing.` : ''}</span></div>
    </section>
  )
}

function HoverTip({ h, st, view }: { h: { kind: string; id: string; x: number; y: number }; st: WState; view: WorldView | null }) {
  const terms = useTerms()
  const host = view?.el.getBoundingClientRect()
  if (!host) return null
  let body: React.ReactNode = null
  if (h.kind === 'unit' && view) {
    const i = view.ids.indexOf(h.id)
    if (i < 0) return null
    const ring = view.ring[i], flag = view.flag[i]
    body = (
      <>
        <div className="tt-title">{view.labels[h.id] ?? h.id}</div>
        <div className="tt-row">{st.families[view.fam[i]]} · {STATES[view.state[i]]}{(flag & 16) ? ' · quiet now' : ''}</div>
        <div className="tt-row">activity {view.h[i] > 0.5 ? 'above' : view.h[i] < -0.5 ? 'below' : 'near'} its usual</div>
        {st.cohorts.find((c) => c.id === st.cohort_ids[view.coh[i]]) && <div className="tt-row muted">{st.cohorts.find((c) => c.id === st.cohort_ids[view.coh[i]])!.label}</div>}
        {ring > 0 && <div className="tt-row" style={{ color: ring === 3 ? 'var(--sev-act)' : ring === 2 ? 'var(--sev-look)' : 'var(--sev-watch)' }}>part of a finding ({['', 'watch', 'look', 'act'][ring]})</div>}
        {(flag & 3) > 0 && <div className="tt-row" style={{ color: 'var(--st-derived)' }}>{flag & 1 ? 'drifting' : 'stands apart from its group'} beyond chance</div>}
      </>
    )
  } else {
    const lm = st.landmarks.find((l) => l.id === h.id)
    if (!lm) return null
    body = (
      <>
        <div className="tt-title">{lm.label}</div>
        <div className="tt-row">{lm.kind} · {lm.events} events now</div>
        <div className="tt-row">{lm.distinct} {terms.agent}s now, usually {lm.usual}{lm.crowding > 1.4 ? ' — a crowd' : ''}</div>
        {lm.teams.length > 0 && <div className="tt-row muted">teams: {lm.teams.join(', ')}</div>}
      </>
    )
  }
  return <div className="world-tip" style={{ left: h.x - host.left + 14, top: h.y - host.top + 14 }}>{body}</div>
}

function Card({ c, spec, onClose, view, onFollow }: { c: { kind: 'unit' | 'landmark'; id: string }; spec?: FullSpec; onClose: () => void; view: WorldView | null; onFollow: (id: string) => void }) {
  const [d, setD] = useState<any>(null)
  const tick = useStore((x) => x.tick)
  const open = useStore((x) => x.openDrawer)
  const show = useStore((x) => x.showToast)
  const terms = useTerms()
  useEffect(() => {
    if (c.kind === 'unit') get(`/api/world/unit/${encodeURIComponent(c.id)}`).then(setD).catch(() => setD(null))
    else get(`/api/world/features?scope=${encodeURIComponent('resource:' + c.id)}`).then(setD).catch(() => setD(null))
  }, [c.id, c.kind, Math.floor(tick / 2)])
  if (!d) return <div className="world-card"><div className="skeleton" style={{ height: 90 }} /></div>
  const scope = c.kind === 'unit' ? `agent:${c.id}` : `resource:${c.id}`
  const control = spec?.control.enabled && c.kind === 'unit'
  return (
    <div className="world-card">
      <div className="row" style={{ alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="label">{c.kind === 'unit' ? terms.agent : terms.resource}</div>
          <div className="display" style={{ fontSize: 21, lineHeight: 1.2 }}>{d.label ?? c.id}</div>
        </div>
        <button className="btn ghost icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
      </div>
      {c.kind === 'unit' ? (
        <div className="stack" style={{ gap: 6, marginTop: 6 }}>
          {d.cohort_label && <div className="muted" style={{ fontSize: 12.5 }}>in {d.cohort_label}</div>}
          {d.task && <div className={`card-task ${d.task.status}`}>{d.task.status === 'inferred' ? 'probably: ' : ''}{d.task.task}<span className="lg-status inferred">{d.task.status}</span></div>}
          <div className="kv mono" style={{ fontSize: 11.5 }}>
            <span className="muted">state</span><span>{d.state} <span className="muted">({d.state_how})</span></span>
            <span className="muted">activity</span><span>{d.activity_now} now · usually {d.activity_usual}</span>
            <span className="muted">drift</span><span>{d.drift}{d.drift_null != null ? <span className="muted"> vs {d.drift_null.toFixed(3)} by chance</span> : null}</span>
            <span className="muted">apart from group</span><span>{d.isolation}{d.isolation_null != null ? <span className="muted"> vs {d.isolation_null.toFixed(2)}</span> : null}</span>
          </div>
          {d.places?.length > 0 && <div className="muted" style={{ fontSize: 12 }}>works on: {d.places.slice(0, 3).map((p: any) => p.label).join(', ')}</div>}
          {d.nearest?.length > 0 && (
            <div className="row" style={{ gap: 4, flexWrap: 'wrap' }}>
              <span className="muted" style={{ fontSize: 12 }}>nearest:</span>
              {d.nearest.slice(0, 5).map((n: any) => <button key={n.unit} className="chip-btn" onClick={() => view?.focusUnit(n.unit)}>{n.label}</button>)}
            </div>
          )}
        </div>
      ) : (
        <div className="kv mono" style={{ fontSize: 11.5, marginTop: 6 }}>
          <span className="muted">now</span><span>{d.distinct_now} {terms.agent}s · {d.events_now} events</span>
          <span className="muted">usually</span><span>{d.distinct_usual} {terms.agent}s</span>
          <span className="muted">crowding</span><span>{d.crowding}{d.crowding_null != null ? <span className="muted"> vs {Number(d.crowding_null).toFixed(2)} by chance</span> : null}</span>
        </div>
      )}
      <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
        {c.kind === 'unit' && <button className="btn sm" onClick={() => onFollow(c.id)}><Icon name="eye" size={12} />Follow</button>}
        <button className="btn sm" onClick={() => open({ kind: 'entity', id: c.id })}>Evidence</button>
        <button className="btn sm" onClick={() => useStore.getState().askCopilot(`In the World, ${d.label ?? c.id} (${scope}): what is it doing, and why is it where it is?`)}><Icon name="chat" size={12} />Ask</button>
        <button className="btn sm ghost" onClick={async () => { await api.question(`What is ${d.label ?? c.id} doing, and does it need attention?`, scope); show('Investigation requested') }}>Investigate</button>
        <button className="btn sm ghost" onClick={async () => { await post('/api/world/ops', { ops: [{ op: 'add_annotation', at: scope, text: `pinned ${new Date().toISOString().slice(11, 16)}` }] }); show('Pinned in the World', true) }}><Icon name="pin" size={12} />Pin</button>
      </div>
      {control && (
        <div className="row" style={{ gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
          <span className="label" style={{ alignSelf: 'center' }}>Control</span>
          {(['pause', 'resume', 'interrupt', 'kill'] as const).map((k) => (
            <button key={k} className={`btn sm ${k === 'kill' ? 'danger' : ''}`} onClick={async () => { await api.control(k, c.id); show(`${k === 'kill' ? 'Stop' : k[0].toUpperCase() + k.slice(1)} sent to ${d.label ?? c.id}`) }}>{k === 'kill' ? 'Stop' : k[0].toUpperCase() + k.slice(1)}</button>
          ))}
        </div>
      )}
    </div>
  )
}

function SelectionBar({ ids, onClear, view }: { ids: string[]; onClear: () => void; view: WorldView | null }) {
  const [sum, setSum] = useState<any>(null)
  const key = useMemo(() => ids.slice(0, 400).join('|'), [ids])
  useEffect(() => { post('/api/world/select', { units: ids.slice(0, 400) }).then(setSum).catch(() => {}) }, [key])
  const terms = useTerms()
  const ask = () => {
    const parts = sum ? [`${sum.units} ${terms.agent}s selected in the World`,
      sum.cohorts?.length ? `groups: ${sum.cohorts.map((c: any) => `${c.label} (${c.n})`).join('; ')}` : '',
      sum.places?.length ? `places: ${sum.places.map((p: any) => p.label).join(', ')}` : '',
      sum.flags && Object.keys(sum.flags).length ? `flags: ${Object.entries(sum.flags).map(([k, v]) => `${v} ${k}`).join(', ')}` : ''].filter(Boolean) : [`${ids.length} ${terms.agent}s selected`]
    useStore.getState().askCopilot(`${parts.join('. ')}. What are these doing together, and does any of it need attention? (sample: ${(sum?.sample ?? ids.slice(0, 8)).join(', ')})`)
  }
  return (
    <div className="world-sel">
      <b>{ids.length} selected</b>
      {sum && <span className="muted">{sum.cohorts?.slice(0, 2).map((c: any) => c.label).join(' · ')}{sum.places?.[0] ? ` · on ${sum.places[0].label}` : ''}</span>}
      <button className="btn sm" onClick={() => view?.focusSet(ids)}>Frame</button>
      <button className="btn sm primary" onClick={ask}><Icon name="chat" size={12} />Ask about these</button>
      <button className="btn sm ghost" onClick={onClear}><Icon name="x" size={12} /></button>
    </div>
  )
}

/** A small, non-interactive World for a dashboard panel: overview camera, click opens the full World. */
/** a compact live World: the dashboard panel, and the Brief's view beside "Needs attention".
 *  interactive: orbit and zoom in place; clicking an agent or place opens it on the World page */
export function WorldMini({ interactive = false }: { interactive?: boolean }) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<WorldView | null>(null)
  const tick = useStore((x) => x.tick)
  const snapWin = useStore((x) => x.snap?.world?.window)
  const ver = useStore((x) => x.snap?.world?.version)
  const [empty, setEmpty] = useState(true)
  const touched = useRef(false)
  useEffect(() => {
    if (!host.current) return
    const v = new WorldView(host.current, interactive ? {
      onClick: (u) => { if (u) useStore.getState().showInWorld(u.kind === 'unit' ? `agent:${u.id}` : `resource:${u.id}`) },
    } : {}, interactive)
    view.current = v
    return () => { v.dispose(); view.current = null }
  }, [interactive])
  useEffect(() => { get<{ spec: WSpec }>('/api/world/spec').then((d) => view.current?.setSpec(d.spec)).catch(() => {}) }, [ver])
  useEffect(() => {
    get<WState>('/api/world/state?ids=1').then((d) => {
      if (d.empty) return
      setEmpty(false)
      view.current?.setState(d)
      if (!touched.current) view.current?.overview()      // keep the whole swarm in frame until someone moves the camera
    }).catch(() => {})
  }, [snapWin ?? tick]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="world-mini" ref={host} onPointerDown={() => { touched.current = true }} onWheel={() => { touched.current = true }} onClick={interactive ? undefined : () => useStore.getState().setRoute('world')} role={interactive ? undefined : 'button'} title={interactive ? undefined : 'Open the World'}>
      {empty && <div className="world-empty"><Empty title="The World fills in as events arrive." /></div>}
    </div>
  )
}

/** the World on the Brief: the live map, what it measures, and what is beyond chance right now */
export function BriefWorld({ s }: { s: Snapshot }) {
  const [metric, setMetric] = useState('')
  const ver = s.world?.version
  useEffect(() => { get<SpecResp>('/api/world/spec').then((d) => setMetric(d.spec.metric?.sentence ?? '')).catch(() => {}) }, [ver])
  const f = s.world?.flags ?? {}
  const chips: [string, string][] = [
    [f.drift ? `${f.drift} drifting` : '', 'drift'], [f.crowding ? `${f.crowding} crowded place${f.crowding > 1 ? 's' : ''}` : '', 'crowding'],
    [f.split ? `${f.split} group${f.split > 1 ? 's' : ''} coming apart` : '', 'split'], [f.still_talking ? `${f.still_talking} talking, not moving` : '', 'still_talking'],
  ].filter(([t]) => t) as [string, string][]
  return (
    <section className="block brief-world">
      <div className="block-head">
        <h2 className="h-section">The World</h2>
        <span style={{ flex: 1 }} />
        <button className="link" onClick={() => useStore.getState().setRoute('world')}>Open <Icon name="arrow" size={13} /></button>
      </div>
      {metric && <div className="bw-metric">{metric}</div>}
      <div className="bw-stage">
        <WorldMini interactive />
        {!s.brief?.catalog && <div className="bw-chips">
          {chips.length ? chips.map(([t, k]) => <button key={k} className="world-chip" onClick={() => useStore.getState().setRoute('world')}><span className="dot" />{t}</button>)
            : <span className="world-chip" style={{ cursor: 'default' }}>Nothing moving beyond chance</span>}
        </div>}
        <div className="bw-hint">drag to orbit · click anything to open it</div>
      </div>
    </section>
  )
}
