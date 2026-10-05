/* The World renderer. Everything visible is bound to a measured quantity (docs/WORLD_PLAN.md §2b); this file only
 * draws what the server computed. Units render in three tiers chosen by population and zoom, so thousands of
 * agents stay at 60 fps:
 *   characters  the cast (characters.ts), ~30 meshes each: small populations, or the few nearest the camera
 *   pawns       one InstancedMesh body + one head: hundreds to ~2,000 units
 *   dots        one Points cloud + cohort blobs from afar: thousands of units
 * Plinths (units that are places) are an instanced column; landmarks are instanced by archetype.
 */
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { CAST, Character, makeCharacter, makeKit, Kit, Pose } from './characters'
import { animMatrix, compile, Compiled, makeModelCharacter, MDef, MScenery } from './models'
import { Act, Choreo, groundLook, softDisc, tileLines, WActs, WBehaviour, WEnv, WEnvSpec, WSceneLegend, zoneColour } from './scene'

/* ------------------------------------------------------------------ wire types */
export interface WLandmark { id: string; label: string; arch: string; kind: string; model?: string | null; fam?: string; x: number; z: number; events: number; distinct: number; usual: number; crowding: number; sev: string | null; new: boolean; teams: string[] }
export interface WRelation { t: string; a: number; b?: number; w?: number; kind?: string; exposed?: boolean }
export interface WCohort { id: string; label: string; n: number; x: number; z: number; r: number; task: string | null; task_status: string | null; task_conf: number | null; stale: boolean; fog: number; split: boolean }
export interface WState {
  empty?: boolean; window: number; now: string; version: number; scale: number; ids_version: number; n: number
  units: Record<'x' | 'z' | 'h' | 'fam' | 'group' | 'state' | 'ring' | 'alpha' | 'cohort' | 'flag', string> & { mix?: string }
  mix_families?: string[]; catalog?: boolean
  families: string[]; groups: string[]; cohort_ids: string[]; landmarks: WLandmark[]; relations: WRelation[]
  cohorts: WCohort[]; territories: { id: string; x: number; z: number; r: number; n: number }[]
  trails: Record<string, [number, number][]>; flags: Record<string, string[]>; null: Record<string, number | null>
  tier: string; ids?: string[]; labels?: Record<string, string>; unavailable?: string[]
  env?: WEnv; acts?: WActs                     // the scene this window, and what each unit did (world/scene.py)
}
export interface WSpec {
  shape: string; unit: { model: string }; render: { tier: string; max_characters: number; character_by: string; character: string; cast?: string[] }; models?: MDef[]; scenery?: MScenery[]; landmarks_from: string; relations: string[]; coverage_fog: boolean; control: { enabled: boolean }
  environment?: WEnvSpec; behaviours?: WBehaviour[]; asset_defs?: MDef[]; scene_legend?: WSceneLegend
}

export const STATES = ['idle', 'active', 'talking', 'working', 'blocked', 'paused', 'stopped']
const POSE: Pose[] = ['idle', 'idle', 'talk', 'work', 'fail', 'wait', 'sleep']

function f32(b64: string) { const s = atob(b64), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return new Float32Array(u.buffer) }
function u8(b64: string) { const s = atob(b64), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return u }
function u16(b64: string) { const s = atob(b64), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return new Uint16Array(u.buffer) }
const hash = (s: string) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) } return (h >>> 0) / 4294967296 }

/* the family palette is the dashboard's (CSS variables), so a workstream has one colour everywhere */
const FAMILY_SLOT: Record<string, number> = { chat: 5, research: 2, docs: 1, code: 6, mail: 3, sheets: 8, social: 7, media: 4, files: 1, shell: 6, search: 2, web: 3, delegation: 4, planning: 8, narration: 7, data: 3, computer: 5 }
function cssVar(name: string, fallback: string) { const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim(); return v || fallback }

interface Theme { bg: THREE.Color; ground: THREE.Color; line: THREE.Color; ink: THREE.Color; ink3: THREE.Color; accent: THREE.Color; act: THREE.Color; look: THREE.Color; watch: THREE.Color; stone: THREE.Color; fam: (f: string) => THREE.Color; night: boolean }
function readTheme(): Theme {
  const c = (n: string, f: string) => new THREE.Color(cssVar(n, f))
  const cats = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => c(`--c${i}`, '#888888'))
  const other = c('--c-other', '#b5ab9c')
  const bg = c('--bg', '#f4efe6')
  return {
    bg, ground: c('--surface', '#fbf9f5'), line: c('--line', '#e2dacd'), ink: c('--ink', '#1f1d1a'), ink3: c('--ink-3', '#857e73'),
    accent: c('--accent', '#cc5a2e'), act: c('--sev-act', '#c2410c'), look: c('--sev-look', '#a87510'), watch: c('--sev-watch', '#8a8378'),
    stone: c('--ink-4', '#b3ab9f'), night: bg.getHSL({ h: 0, s: 0, l: 0 }).l < 0.3,
    // known workstreams keep the dashboard's colours; any other family (e.g. a method class) gets a stable slot
    fam: (f: string) => { const i = FAMILY_SLOT[f]; return i ? cats[i - 1] : f && f !== 'other' ? cats[Math.floor(hash(f) * 8)] : other },
  }
}

export interface ViewEvents {
  onHover?: (u: { kind: 'unit' | 'landmark'; id: string; index?: number } | null, x: number, y: number) => void
  onClick?: (u: { kind: 'unit' | 'landmark'; id: string } | null) => void
  onSelect?: (ids: string[]) => void
}

const MAX = 6000

export class WorldView {
  el: HTMLElement
  renderer: THREE.WebGLRenderer
  scene = new THREE.Scene()
  camera: THREE.PerspectiveCamera
  controls: OrbitControls
  theme: Theme
  kit: Kit
  ev: ViewEvents
  interactive: boolean
  spec: WSpec | null = null
  st: WState | null = null
  ids: string[] = []
  labels: Record<string, string> = {}
  // decoded per-unit arrays
  x0 = new Float32Array(0); z0 = new Float32Array(0); x1 = new Float32Array(0); z1 = new Float32Array(0)
  h = new Float32Array(0); fam = new Uint8Array(0); grp = new Uint16Array(0); state = new Uint8Array(0); ring = new Uint8Array(0)
  alpha = new Uint8Array(0); coh = new Uint16Array(0); flag = new Uint8Array(0)
  mix = new Uint8Array(0)                       // catalogs: per unit, the share of each method (0-255)
  plinthOwner: { solid: number[]; glass: number[] } = { solid: [], glass: [] }
  tStart = 0
  // layers
  ground!: THREE.Mesh
  grid!: THREE.LineSegments
  dots!: THREE.Points
  pawnBody!: THREE.InstancedMesh
  pawnHead!: THREE.InstancedMesh
  plinthSolid!: THREE.InstancedMesh
  plinthGlass!: THREE.InstancedMesh
  rings!: THREE.InstancedMesh
  halos!: THREE.InstancedMesh
  bubbles!: THREE.InstancedMesh
  beams!: THREE.InstancedMesh
  blobs!: THREE.InstancedMesh
  territories!: THREE.InstancedMesh
  fog!: THREE.InstancedMesh
  lmMeshes: Record<string, THREE.InstancedMesh> = {}
  // models made for this stream: compiled once per spec and theme, drawn instanced
  custom: Record<string, { c: Compiled; ims: THREE.InstancedMesh[]; base: THREE.Matrix4[]; order: string[]; phase: number[] }> = {}
  modelKey = ''
  // the scene (ground style, zones, props) and the activity choreography
  tiles!: THREE.LineSegments
  water!: THREE.Mesh
  zones!: THREE.InstancedMesh
  pulses!: THREE.InstancedMesh
  glows!: THREE.InstancedMesh
  tokens!: THREE.InstancedMesh
  choreo = new Choreo()
  act: Act = { x: 0, z: 0, moving: false, pose: null, pulse: 0, glow: 0, fade: 0, carry: null }
  cx = new Float32Array(0); cz = new Float32Array(0); cfade = new Float32Array(0); cpose: (string | null)[] = []
  lastApply = 0
  period = 5000                                  // ms between windows, smoothed: excursions spread over it
  heat!: THREE.InstancedMesh
  trails = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ transparent: true, opacity: 0.45 }))
  arcs = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.55 }))
  dashed = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ dashSize: 0.25, gapSize: 0.2, transparent: true, opacity: 0.6 }))
  chars = new Map<string, Character>()
  charLayer = new THREE.Group()
  tier = 'pawns'
  // overlays
  overlay: HTMLDivElement
  rect: HTMLDivElement
  follow: string | null = null
  insetRight = 0                                 // px of the stage covered on the right (the legend)
  camGoal: { target: THREE.Vector3; pos: THREE.Vector3 } | null = null
  raf = 0
  clock = new THREE.Clock()
  ray = new THREE.Raycaster()
  lastHover = 0
  pending: { x: number; y: number } | null = null
  drag: { x: number; y: number } | null = null
  mat4 = new THREE.Matrix4()
  q = new THREE.Quaternion()
  v = new THREE.Vector3()
  s3 = new THREE.Vector3()
  col = new THREE.Color()
  disposed = false
  labelEls: HTMLDivElement[] = []

  constructor(el: HTMLElement, ev: ViewEvents = {}, interactive = true) {
    this.el = el
    this.ev = ev
    this.interactive = interactive
    this.theme = readTheme()
    this.kit = makeKit(this.theme.night)
    this.watchTheme()
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.outputColorSpace = THREE.SRGBColorSpace
    el.appendChild(this.renderer.domElement)
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 2000)
    this.camera.position.set(0, 30, 38)
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.08
    this.controls.maxPolarAngle = 1.38
    this.controls.minDistance = 2.5
    this.controls.screenSpacePanning = false
    this.controls.enabled = interactive
    this.overlay = document.createElement('div')
    this.overlay.className = 'world-overlay'
    el.appendChild(this.overlay)
    this.rect = document.createElement('div')
    this.rect.className = 'world-rect'
    el.appendChild(this.rect)
    this.build()
    this.resize()
    new ResizeObserver(() => this.resize()).observe(el)
    if (interactive) this.bindInput()
    this.loop()
  }

  /* ---------------------------------------------------------------- scene graph */
  build() {
    const T = this.theme, S = this.scene
    S.background = T.bg.clone()
    S.fog = new THREE.Fog(T.bg.clone(), 80, 260)
    S.add(new THREE.HemisphereLight(0xffffff, T.night ? 0x202020 : 0xd8cfc0, T.night ? 0.7 : 1.15))
    const sun = new THREE.DirectionalLight(0xffffff, T.night ? 0.8 : 1.6)
    sun.position.set(30, 60, 20)
    S.add(sun)
    this.ground = new THREE.Mesh(new THREE.CircleGeometry(1, 96), new THREE.MeshStandardMaterial({ color: T.ground, roughness: 1 }))
    this.ground.rotation.x = -Math.PI / 2
    S.add(this.ground)
    // polar grid: rings and spokes, faint
    const gp: number[] = []
    for (let r = 1; r <= 4; r++) for (let i = 0; i < 96; i++) {
      const a0 = (i / 96) * Math.PI * 2, a1 = ((i + 1) / 96) * Math.PI * 2
      gp.push(Math.cos(a0) * r / 4, 0.01, Math.sin(a0) * r / 4, Math.cos(a1) * r / 4, 0.01, Math.sin(a1) * r / 4)
    }
    for (let i = 0; i < 16; i++) { const a = (i / 16) * Math.PI * 2; gp.push(0, 0.01, 0, Math.cos(a), 0.01, Math.sin(a)) }
    const gg = new THREE.BufferGeometry(); gg.setAttribute('position', new THREE.Float32BufferAttribute(gp, 3))
    this.grid = new THREE.LineSegments(gg, new THREE.LineBasicMaterial({ color: T.line, transparent: true, opacity: 0.7 }))
    S.add(this.grid)
    const inst = (g: THREE.BufferGeometry, m: THREE.Material, n = MAX) => { const im = new THREE.InstancedMesh(g, m, n); im.count = 0; im.frustumCulled = false; S.add(im); return im }
    const std = (o: THREE.MeshStandardMaterialParameters = {}) => new THREE.MeshStandardMaterial({ roughness: 0.7, ...o })
    const flat = (g: THREE.BufferGeometry) => { g.rotateX(-Math.PI / 2); return g }
    // ground styles: square tiles, a water edge; zones are soft tinted discs under everything else
    this.tiles = new THREE.LineSegments(tileLines(), new THREE.LineBasicMaterial({ color: T.line, transparent: true, opacity: 0.5 }))
    this.tiles.visible = false
    S.add(this.tiles)
    this.water = new THREE.Mesh(flat(new THREE.RingGeometry(1, 1.35, 96)), new THREE.MeshStandardMaterial({ roughness: 0.4 }))
    this.water.position.y = 0.004
    this.water.visible = false
    S.add(this.water)
    this.zones = inst(flat(new THREE.CircleGeometry(1, 40)), new THREE.MeshBasicMaterial({ transparent: true, opacity: T.night ? 0.42 : 0.5, alphaMap: softDisc(), depthWrite: false }), 240)
    this.zones.position.y = 0.003
    this.pulses = inst(flat(new THREE.RingGeometry(0.42, 0.5, 32)), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.8, depthWrite: false }), 1500)
    this.pulses.position.y = 0.035
    this.glows = inst(flat(new THREE.CircleGeometry(0.62, 24)), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.45, alphaMap: softDisc(), depthWrite: false, blending: THREE.AdditiveBlending }), 1500)
    this.glows.position.y = 0.04
    this.tokens = inst(new THREE.OctahedronGeometry(0.13, 0), new THREE.MeshBasicMaterial({ color: new THREE.Color(cssVar('--st-self', '#9c58c2')) }), 600)
    this.territories = inst(flat(new THREE.RingGeometry(0.965, 1, 64)),new THREE.MeshBasicMaterial({ transparent: true, opacity: T.night ? 0.55 : 0.6, depthWrite: false }), 64)
    this.blobs = inst(flat(new THREE.CircleGeometry(1, 40)), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.35, depthWrite: false }), 600)
    this.fog = inst(flat(new THREE.CircleGeometry(1, 40)), new THREE.MeshBasicMaterial({ color: T.night ? 0x9aa3a6 : 0xffffff, transparent: true, opacity: T.night ? 0.06 : 0.16, depthWrite: false }), 600)
    this.fog.position.y = 0.55
    // units
    const dg = new THREE.BufferGeometry()
    dg.setAttribute('position', new THREE.BufferAttribute(new Float32Array(MAX * 3), 3))
    dg.setAttribute('color', new THREE.BufferAttribute(new Float32Array(MAX * 3), 3))
    this.dots = new THREE.Points(dg, new THREE.PointsMaterial({ size: 0.45, vertexColors: true, sizeAttenuation: true, transparent: true, opacity: 0.95 }))
    this.dots.frustumCulled = false
    S.add(this.dots)
    this.pawnBody = inst(new THREE.CapsuleGeometry(0.17, 0.32, 4, 10).translate(0, 0.34, 0), std({ roughness: 0.6 }))
    this.pawnHead = inst(new THREE.SphereGeometry(0.15, 14, 10).translate(0, 0.78, 0), std({ color: T.night ? 0xe9ddd2 : 0xf1e4da, roughness: 0.6 }))
    this.plinthSolid = inst(new THREE.BoxGeometry(0.55, 1, 0.55).translate(0, 0.5, 0), std({ roughness: 0.55 }))
    this.plinthGlass = inst(new THREE.BoxGeometry(0.55, 1, 0.55).translate(0, 0.5, 0), std({ roughness: 0.2, transparent: true, opacity: 0.45 }))
    this.rings = inst(flat(new THREE.RingGeometry(0.32, 0.42, 28)), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.95, depthWrite: false }))
    this.rings.position.y = 0.03
    this.halos = inst(new THREE.CylinderGeometry(0.05, 0.05, 1, 6).translate(0, 0.5, 0), new THREE.MeshBasicMaterial({ color: T.night ? 0xbfe8ff : 0x2f7db5, transparent: true, opacity: 0.55 }), 400)
    this.bubbles = inst(new THREE.SphereGeometry(0.09, 10, 8), new THREE.MeshBasicMaterial({ color: T.night ? 0xffffff : 0xffffff }), 1500)
    this.beams = inst(new THREE.CylinderGeometry(0.12, 0.12, 1, 10, 1, true).translate(0, 0.5, 0), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.5, side: THREE.DoubleSide, depthWrite: false }), 400)
    // landmarks by archetype
    const stone = std({ color: T.night ? 0x5f594f : 0xd9cfbf, roughness: 0.9 })
    const lg: Record<string, THREE.BufferGeometry> = {
      slab: new THREE.BoxGeometry(1.3, 0.22, 0.95).translate(0, 0.11, 0),
      tower: new THREE.BoxGeometry(0.55, 2.4, 0.55).translate(0, 1.2, 0),
      plaza: new THREE.CylinderGeometry(1.0, 1.05, 0.08, 28).translate(0, 0.04, 0),
      kiosk: new THREE.BoxGeometry(0.42, 0.9, 0.42).translate(0, 0.45, 0),
      road: new THREE.BoxGeometry(1, 0.03, 0.35).translate(0.5, 0.015, 0),
      gate: new THREE.TorusGeometry(0.6, 0.08, 6, 16, Math.PI),
      district: flat(new THREE.CircleGeometry(1, 32)),
    }
    for (const [k, g] of Object.entries(lg)) this.lmMeshes[k] = inst(g, k === 'road' ? std({ color: T.night ? 0x46595b : 0xddd2bd, roughness: 1 }) : stone, 400)
    this.heat = inst(flat(new THREE.RingGeometry(0.9, 1.0, 40)), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.85, depthWrite: false }), 400)
    this.heat.position.y = 0.02
    for (const l of [this.trails, this.arcs, this.dashed]) { l.frustumCulled = false; S.add(l) }
    ;(this.trails.material as THREE.LineBasicMaterial).color = T.ink3.clone()
    ;(this.dashed.material as THREE.LineDashedMaterial).color = new THREE.Color(cssVar('--st-self', '#9c58c2'))
    S.add(this.charLayer)
  }

  resize() {
    const w = this.el.clientWidth || 600, h = this.el.clientHeight || 400
    this.renderer.setSize(w, h, false)
    this.renderer.domElement.style.width = '100%'
    this.renderer.domElement.style.height = '100%'
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }

  setTheme() {
    const T = (this.theme = readTheme())
    this.scene.background = T.bg.clone()
    ;(this.scene.fog as THREE.Fog).color = T.bg.clone()
    ;(this.ground.material as THREE.MeshStandardMaterial).color = T.ground.clone()
    this.kit.dispose()
    this.kit = makeKit(T.night)
    this.chars.forEach((c) => c.dispose())
    this.chars.clear()
    this.modelKey = ''
    ;(this.tokens.material as THREE.MeshBasicMaterial).color = new THREE.Color(cssVar('--st-self', '#9c58c2'))
    ;(this.tiles.material as THREE.LineBasicMaterial).color = T.line.clone()
    if (this.spec) this.buildModels(this.spec)
    if (this.st) this.applyState(this.st, false)
  }

  /* ---------------------------------------------------------------- data in */
  setSpec(spec: WSpec) {
    const castKey = (x: WSpec) => JSON.stringify([x.render.character_by, x.render.character, x.render.cast ?? null, (x.models ?? []).filter((m) => m.kind === 'unit')])
    const changed = !this.spec || castKey(this.spec) !== castKey(spec)
    this.spec = spec
    if (changed) { this.chars.forEach((c) => c.dispose()); this.chars.clear() }
    this.buildModels(spec)
    if (this.st) { this.buildChoreo(this.choreo.start || performance.now()); this.drawStatic() }
  }

  /** the activity rules for this window: each unit's excursion, spread over the time until the next window */
  buildChoreo(start: number) {
    const st = this.st
    if (!st) return
    const cent = new Map(st.cohorts.map((c) => [c.id, [c.x, c.z] as [number, number]]))
    this.choreo.build({
      ids: this.ids, hx: this.x1, hz: this.z1, acts: st.acts, behaviours: this.spec?.behaviours ?? [],
      landmarks: st.landmarks, centre: (i) => cent.get(st.cohort_ids[this.coh[i]]) ?? [0, 0],
    }, start, this.period * 0.92)
  }

  /** compile landmark and scenery models into instanced meshes (once per change of the models or the theme) */
  buildModels(spec: WSpec) {
    const key = JSON.stringify(spec.models ?? []) + JSON.stringify((spec.asset_defs ?? []).map((a) => a.id)) + '|' + this.theme.night
    if (key === this.modelKey) return
    this.modelKey = key
    for (const e of Object.values(this.custom)) for (const im of e.ims) { this.scene.remove(im); im.geometry.dispose(); (im.material as THREE.Material).dispose() }
    this.custom = {}
    for (const def of spec.models ?? []) {
      if (def.kind === 'unit') continue
      const prop = def.kind === 'prop'
      const c = compile(def, this.theme.night, prop, this.theme.ground)
      const cap = prop ? 60 : 400
      const ims = c.meshes.map((cm) => {
        const im = new THREE.InstancedMesh(cm.geo, cm.mat, cap)
        im.count = 0; im.frustumCulled = false
        if (cm.tint) for (let k = 0; k < cap; k++) im.setColorAt(k, this.col.set(0xffffff))
        this.scene.add(im)
        return im
      })
      this.custom[def.id] = { c, ims, base: [], order: [], phase: [] }
    }
    // library props the environment places: compiled like any model, pulled further toward the ground (muted)
    for (const def of spec.asset_defs ?? []) {
      const c = compile(def, this.theme.night, true, this.theme.ground, this.theme.night ? 0.42 : 0.38)
      const cap = 480
      const ims = c.meshes.map((cm) => { const im = new THREE.InstancedMesh(cm.geo, cm.mat, cap); im.count = 0; im.frustumCulled = false; this.scene.add(im); return im })
      this.custom['asset:' + def.id] = { c, ims, base: [], order: [], phase: [] }
    }
  }

  /** place one instance of a compiled model; animated parts are placed every frame from `base` */
  private placeModel(id: string, base: THREE.Matrix4, tint: THREE.Color | null, key: string) {
    const e = this.custom[id]
    const k = e.order.length
    if (k >= e.ims[0]?.instanceMatrix.count) return
    e.order.push(key); e.base.push(base.clone()); e.phase.push(hash(key))
    e.c.meshes.forEach((cm, j) => {
      const im = e.ims[j]
      if (!cm.anim) im.setMatrixAt(k, base)
      if (cm.tint && tint) im.setColorAt(k, tint)
    })
  }

  private animateModels(t: number) {
    const m = this.mat4, a = new THREE.Matrix4()
    for (const e of Object.values(this.custom)) e.c.meshes.forEach((cm, j) => {
      if (!cm.anim) return
      const im = e.ims[j]
      for (let k = 0; k < e.order.length; k++) {
        m.multiplyMatrices(e.base[k], cm.at).multiply(animMatrix(cm.anim, t, e.phase[k], a)).multiply(cm.rot)
        im.setMatrixAt(k, m)
      }
      im.instanceMatrix.needsUpdate = true
    })
  }

  setState(st: WState) {
    if (st.empty) return
    const first = !this.st
    this.applyState(st, true)
    if (first) this.overview(false)
  }

  private applyState(st: WState, animate: boolean) {
    const ids = st.ids ?? this.ids
    if (st.labels && Object.keys(st.labels).length) this.labels = st.labels
    const x = f32(st.units.x), z = f32(st.units.z)
    // previous positions, remapped by id when the unit list changed
    const prev = new Map<string, [number, number]>()
    const t = this.progress()
    for (let i = 0; i < this.ids.length; i++) prev.set(this.ids[i], [this.x0[i] + (this.x1[i] - this.x0[i]) * t, this.z0[i] + (this.z1[i] - this.z0[i]) * t])
    const n = ids.length
    this.x0 = new Float32Array(n); this.z0 = new Float32Array(n)
    for (let i = 0; i < n; i++) { const p = prev.get(ids[i]); this.x0[i] = p ? p[0] : x[i]; this.z0[i] = p ? p[1] : z[i] }
    if (!animate) { this.x0.set(x); this.z0.set(z) }
    this.x1 = x; this.z1 = z
    this.ids = ids
    this.h = f32(st.units.h); this.fam = u8(st.units.fam); this.grp = u16(st.units.group); this.state = u8(st.units.state)
    this.ring = u8(st.units.ring); this.alpha = u8(st.units.alpha); this.coh = u16(st.units.cohort); this.flag = u8(st.units.flag)
    this.mix = st.units.mix ? u8(st.units.mix) : new Uint8Array(0)
    this.st = st
    const now = performance.now()
    if (animate && this.lastApply) this.period = this.period * 0.6 + Math.max(1500, Math.min(30000, now - this.lastApply)) * 0.4
    if (animate) this.lastApply = now
    this.tStart = now
    this.buildChoreo(now)
    const S = st.scale
    this.ground.scale.setScalar(S * 1.25)
    this.grid.scale.setScalar(S * 1.05)
    this.tiles.scale.setScalar(S * 1.2)
    this.water.scale.setScalar(S * 1.25)
    ;(this.scene.fog as THREE.Fog).near = S * 2.2
    ;(this.scene.fog as THREE.Fog).far = S * 6
    this.chooseTier()
    this.drawStatic()
  }

  plinthHeight(h: number) { return 0.4 + Math.max(0, Math.min(2.6, (h + 1) * 0.65)) * (this.st?.catalog ? 1.6 : 1) }

  progress() { return Math.min(1, (performance.now() - this.tStart) / 800) }

  chooseTier() {
    const st = this.st!, spec = this.spec
    const want = spec?.render.tier && spec.render.tier !== 'auto' ? spec.render.tier : st.tier
    const dist = this.camera.position.distanceTo(this.controls.target)
    const near = dist < Math.max(10, st.scale * 0.55)
    this.tier = this.spec?.unit.model === 'plinth' ? 'plinths' : want === 'dots' && near ? 'pawns' : want
  }

  /* things that only change with the state: landmarks, territories, fog, trails, arcs, blobs */
  drawStatic() {
    const st = this.st!, T = this.theme, m = this.mat4, q = this.q
    this.drawEnvironment()
    // territories
    st.territories.slice(0, 64).forEach((t, i) => {
      m.compose(this.v.set(t.x, 0.005, t.z), q.identity(), this.s3.setScalar(Math.min(t.r, st.scale * 0.45)))
      this.territories.setMatrixAt(i, m)
      this.territories.setColorAt(i, this.col.setHSL(hash(t.id), 0.45, T.night ? 0.45 : 0.6))
    })
    this.territories.count = Math.min(64, st.territories.length)
    this.bump(this.territories)
    // fog over cohorts that have not been read closely
    // fog: a soft haze over groups nobody has read closely for a while (largest first, capped, never inflated)
    let fi = 0
    for (const c of [...st.cohorts].filter((c) => c.fog >= 12 && c.n >= 3).sort((a, b) => b.n - a.n).slice(0, 40)) {
      m.compose(this.v.set(c.x, 0, c.z), q.identity(), this.s3.set(c.r * 0.9, 1, c.r * 0.9))
      this.fog.setMatrixAt(fi++, m)
    }
    this.fog.count = this.spec?.coverage_fog === false ? 0 : fi
    this.bump(this.fog)
    // cohort blobs (dots tier, from afar)
    const famCount = new Map<number, Map<number, number>>()
    for (let i = 0; i < this.ids.length; i++) { const c = this.coh[i]; const mm = famCount.get(c) ?? new Map(); mm.set(this.fam[i], (mm.get(this.fam[i]) ?? 0) + 1); famCount.set(c, mm) }
    st.cohorts.slice(0, 600).forEach((c, i) => {
      m.compose(this.v.set(c.x, 0.02, c.z), q.identity(), this.s3.set(c.r, 1, c.r))
      this.blobs.setMatrixAt(i, m)
      const ci = st.cohort_ids.indexOf(c.id)
      const fm = famCount.get(ci)
      const top = fm ? [...fm.entries()].sort((a, b) => b[1] - a[1])[0][0] : 0
      this.blobs.setColorAt(i, T.fam(st.families[top] ?? 'other'))
    })
    this.blobs.count = Math.min(600, st.cohorts.length)
    this.bump(this.blobs)
    // landmarks (and the models made for this stream)
    const counts: Record<string, number> = {}
    let hi = 0
    for (const e of Object.values(this.custom)) { e.order = []; e.base = []; e.phase = [] }
    for (const lm of st.landmarks) {
      const size = 0.7 + Math.min(1.6, Math.log1p(lm.events) / 3)
      if (lm.model && this.custom[lm.model]) {
        const sc = 0.75 + Math.min(0.6, Math.log1p(lm.events) / 6)
        m.compose(this.v.set(lm.x, 0, lm.z), q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), hash(lm.id) * 0.6 - 0.3), this.s3.setScalar(sc))
        this.placeModel(lm.model, m, T.fam(lm.fam ?? ''), lm.id)
      } else {
      const arch = this.lmMeshes[lm.arch] ? lm.arch : 'kiosk'
      const k = counts[arch] = (counts[arch] ?? 0)
      if (k >= 400) continue
      if (arch === 'road') {
        const len = Math.hypot(lm.x, lm.z), ang = Math.atan2(lm.z, lm.x)
        m.compose(this.v.set(0, 0, 0), q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), -ang), this.s3.set(len, 1, 0.6 + Math.log1p(lm.events) / 4))
      } else {
        m.compose(this.v.set(lm.x, 0, lm.z), q.identity(), this.s3.set(size, arch === 'tower' ? 0.6 + size * 0.35 : 1, size))
      }
      this.lmMeshes[arch].setMatrixAt(k, m)
      counts[arch] = k + 1
      }
      // crowd ring: distinct units vs usual (the convergence quantity); severity colours only for findings
      if (lm.crowding > 1.25 && hi < 400) {
        const r = 1.1 * size + Math.min(2.5, (lm.crowding - 1) * 1.2)
        m.compose(this.v.set(lm.x, 0, lm.z), q.identity(), this.s3.set(r, 1, r))
        this.heat.setMatrixAt(hi, m)
        this.heat.setColorAt(hi, lm.sev === 'ACT' ? T.act : lm.sev === 'LOOK' ? T.look : this.col.copy(T.accent).lerp(T.ground, 0.45))
        hi++
      }
    }
    for (const [k, im] of Object.entries(this.lmMeshes)) { im.count = counts[k] ?? 0; this.bump(im) }
    this.placeScenery()
    this.placeProps()
    for (const e of Object.values(this.custom)) for (const im of e.ims) { im.count = e.order.length; this.bump(im) }
    this.heat.count = hi
    this.bump(this.heat)
    // trails
    const tp: number[] = []
    for (const pts of Object.values(st.trails)) for (let i = 1; i < pts.length; i++) tp.push(pts[i - 1][0], 0.06, pts[i - 1][1], pts[i][0], 0.06, pts[i][1])
    this.trails.geometry.dispose()
    this.trails.geometry = new THREE.BufferGeometry()
    this.trails.geometry.setAttribute('position', new THREE.Float32BufferAttribute(tp, 3))
    this.drawArcs()
  }

  /** the ground style and the zones: decoration that says what kind of place a region is, never a measurement */
  drawEnvironment() {
    const st = this.st!, T = this.theme, m = this.mat4, q = this.q
    const look = groundLook(st.env?.ground ?? this.spec?.environment?.ground, T.ground, T.night)
    ;(this.ground.material as THREE.MeshStandardMaterial).color = look.colour
    this.grid.visible = look.grid === 'polar'
    ;(this.grid.material as THREE.LineBasicMaterial).opacity = look.gridAlpha
    this.tiles.visible = look.grid === 'tiles'
    ;(this.tiles.material as THREE.LineBasicMaterial).opacity = look.gridAlpha
    this.water.visible = look.water
    ;(this.water.material as THREE.MeshStandardMaterial).color = zoneColour('water', T.ground, T.night)
    let k = 0
    for (const z of st.env?.zones ?? []) {
      const col = zoneColour(z.style, look.colour, T.night)
      for (const [x, zz, r] of z.discs) {
        if (k >= 240) break
        m.compose(this.v.set(x, 0, zz), q.identity(), this.s3.set(r, 1, r))
        this.zones.setMatrixAt(k, m); this.zones.setColorAt(k, col); k++
      }
    }
    this.zones.count = k
    this.bump(this.zones)
  }

  /** environment props, placed by the server from the landmarks (deterministic), drawn instanced and muted */
  placeProps() {
    const props = this.st?.env?.props ?? {}, m = this.mat4, q = this.q, up = new THREE.Vector3(0, 1, 0)
    for (const [asset, arr] of Object.entries(props)) {
      const id = 'asset:' + asset
      const made = this.custom[id] ? id : this.custom[asset]?.c.kind === 'prop' ? asset : null
      if (!made) continue
      for (let k = 0; k + 2 < arr.length; k += 3) {
        m.compose(this.v.set(arr[k], 0, arr[k + 1]), q.setFromAxisAngle(up, arr[k + 2]), this.s3.setScalar(1))
        this.placeModel(made, m, null, `${asset}:${k}`)
      }
    }
  }

  /** scenery: props at the centre, around the rim, or beside each group's territory; encodes nothing */
  placeScenery() {
    const st = this.st!, m = this.mat4, q = this.q, S = st.scale
    const up = new THREE.Vector3(0, 1, 0)
    for (const sc of this.spec?.scenery ?? []) {
      if (!this.custom[sc.model]) continue
      const spots: [number, number][] = []
      if (sc.at === 'centre') spots.push([0, 0])
      else if (sc.at === 'rim') { const n = Math.max(1, Math.min(24, sc.count || 8)); for (let i = 0; i < n; i++) { const a = (i / n) * Math.PI * 2; spots.push([Math.cos(a) * S * 1.15, Math.sin(a) * S * 1.15]) } }
      else for (const t of st.territories.slice(0, 24)) { const d = Math.hypot(t.x, t.z) || 1; const r = Math.min(t.r, S * 0.45) + 0.8; spots.push([t.x + (t.x / d) * r, t.z + (t.z / d) * r]) }
      spots.forEach(([x, z], i) => {
        m.compose(this.v.set(x, 0, z), q.setFromAxisAngle(up, -Math.atan2(z, x) - Math.PI / 2), this.s3.setScalar(1))
        this.placeModel(sc.model, m, null, `${sc.model}:${sc.at}:${i}`)
      })
    }
  }

  drawArcs() {
    const st = this.st!, T = this.theme
    const ap: number[] = [], ac: number[] = [], dp: number[] = []
    const cTouch = T.ink3.clone().lerp(T.ground, 0.3), cReply = new THREE.Color(cssVar('--st-derived', '#2f7db5')), cLin = new THREE.Color(cssVar('--st-self', '#9c58c2'))
    const pos = (i: number) => { const t = this.progress(); return [this.x0[i] + (this.x1[i] - this.x0[i]) * t, this.z0[i] + (this.z1[i] - this.z0[i]) * t] }
    const close = this.camera.position.distanceTo(this.controls.target) < st.scale * 0.9
    let drawn = 0
    for (const r of st.relations) {
      if (r.t === 'beam' || r.b == null || r.a >= this.ids.length || r.b >= this.ids.length) continue
      if (r.t === 'co_touch' && !close) continue          // implied by the landmarks from afar; drawn when zoomed in
      if (++drawn > (close ? 300 : 120)) break
      const [ax, az] = pos(r.a), [bx, bz] = pos(r.b)
      const lift = Math.min(3, Math.hypot(bx - ax, bz - az) * 0.25) + 0.3
      const col = r.t === 'reply' ? cReply : r.t === 'lineage' ? cLin : cTouch
      const target = r.t === 'lineage' && !r.exposed ? dp : ap
      let px = ax, py = 0.5, pz = az
      for (let s = 1; s <= 8; s++) {
        const u = s / 8, x = ax + (bx - ax) * u, z = az + (bz - az) * u, y = 0.5 + Math.sin(u * Math.PI) * lift
        target.push(px, py, pz, x, y, z)
        if (target === ap) ac.push(col.r, col.g, col.b, col.r, col.g, col.b)
        px = x; py = y; pz = z
      }
    }
    this.arcs.geometry.dispose()
    this.arcs.geometry = new THREE.BufferGeometry()
    this.arcs.geometry.setAttribute('position', new THREE.Float32BufferAttribute(ap, 3))
    this.arcs.geometry.setAttribute('color', new THREE.Float32BufferAttribute(ac, 3))
    this.dashed.geometry.dispose()
    this.dashed.geometry = new THREE.BufferGeometry()
    this.dashed.geometry.setAttribute('position', new THREE.Float32BufferAttribute(dp, 3))
    this.dashed.computeLineDistances()
  }

  bump(im: THREE.InstancedMesh) { im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true }

  /* ---------------------------------------------------------------- per frame: units move between windows */
  frame(t: number) {
    if (!this.st) return
    const T = this.theme, n = this.ids.length, p = this.progress(), m = this.mat4, q = this.q
    const ease = p < 1 ? p * p * (3 - 2 * p) : 1
    const X = (i: number) => this.x0[i] + (this.x1[i] - this.x0[i]) * ease
    const Z = (i: number) => this.z0[i] + (this.z1[i] - this.z0[i]) * ease
    const famC = this.st.families.map((f) => T.fam(f))
    const mixC = (this.st.mix_families ?? []).map((f) => T.fam(f))
    const mixK = mixC.length
    this.plinthOwner = { solid: [], glass: [] }
    this.chooseTier()
    const tier = this.tier
    const showDots = tier === 'dots', showPawns = tier === 'pawns' || tier === 'characters', showPlinths = tier === 'plinths'
    // characters: all units in a small world, or the ~40 nearest the camera target when zoomed in
    const charIdx = new Set<number>()
    if (this.spec?.unit.model !== 'plinth') {
      const dist = this.camera.position.distanceTo(this.controls.target)
      if (tier === 'characters' && n <= (this.spec?.render.max_characters ?? 80)) for (let i = 0; i < n; i++) charIdx.add(i)
      else if (dist < Math.max(9, this.st.scale * 0.35)) {
        const tx = this.controls.target.x, tz = this.controls.target.z
        const near = [...Array(n).keys()].map((i) => [i, (X(i) - tx) ** 2 + (Z(i) - tz) ** 2]).sort((a, b) => a[1] - b[1]).slice(0, 40)
        near.forEach(([i]) => charIdx.add(i))
      }
    }
    // dots
    const dpos = this.dots.geometry.getAttribute('position') as THREE.BufferAttribute
    const dcol = this.dots.geometry.getAttribute('color') as THREE.BufferAttribute
    let di = 0, pi = 0, si = 0, gi = 0, ri = 0, hi = 0, bi = 0, pu = 0, gl = 0, tk = 0
    // activity rules: excursions from the measured position (not in the dots tier, which stays cheap)
    const choreo = tier !== 'dots' && this.choreo.active > 0, now = performance.now(), A = this.act
    if (this.cx.length !== n) { this.cx = new Float32Array(n); this.cz = new Float32Array(n); this.cfade = new Float32Array(n); this.cpose = new Array(n).fill(null) }
    for (let i = 0; i < n; i++) {
      let x = X(i), z = Z(i), fade = 0, walking = false, pose: string | null = null
      const hh = this.h[i], st = this.state[i], quiet = (this.flag[i] & 16) !== 0
      const fc = famC[this.fam[i]] ?? famC[0]
      if (choreo && this.choreo.at(i, now, x, z, A)) {
        x = A.x; z = A.z; fade = A.fade; walking = A.moving; pose = A.pose
        if (A.pulse && pu < 1500) {
          const r = (showPlinths ? 1.6 : 1) * (0.7 + A.pulse * 1.6)
          m.compose(this.v.set(x, 0, z), q.identity(), this.s3.set(r, 1, r))
          this.pulses.setMatrixAt(pu, m); this.pulses.setColorAt(pu, this.col.copy(fc).lerp(T.ground, A.pulse * 0.85)); pu++
        }
        if (A.glow && gl < 1500) {
          m.compose(this.v.set(x, 0, z), q.identity(), this.s3.setScalar(0.6 + A.glow * 0.7))
          this.glows.setMatrixAt(gl, m); this.glows.setColorAt(gl, this.col.copy(fc).lerp(T.ink, T.night ? 0.25 : 0).multiplyScalar(A.glow)); gl++
        }
        if (A.carry && tk < 600) {
          m.compose(A.carry, q.setFromAxisAngle(this.s3.set(0, 1, 0), t * 3 + i), this.s3.setScalar(1))
          this.tokens.setMatrixAt(tk++, m)
        }
      }
      this.cx[i] = x; this.cz[i] = z; this.cfade[i] = fade; this.cpose[i] = pose
      const height = 0.75 + Math.max(-0.25, Math.min(1.0, hh * 0.28))
      const dim = quiet ? 0.45 : 1
      if (showPlinths) {
        const hgt = this.plinthHeight(hh)
        const glass = this.alpha[i] < 200
        const im = glass ? this.plinthGlass : this.plinthSolid
        const owners = glass ? this.plinthOwner.glass : this.plinthOwner.solid
        const mk = mixK && this.mix.length >= (i + 1) * mixK ? mixK : 0
        if (mk) {                                     // one band per method, bottom to top in corner order
          let y0 = 0
          for (let j = 0; j < mk; j++) {
            const share = this.mix[i * mk + j] / 255
            if (share < 0.004) continue
            const seg = hgt * share
            const k = glass ? gi++ : pi++
            m.compose(this.v.set(x, y0, z), q.identity(), this.s3.set(1, seg, 1))
            im.setMatrixAt(k, m); im.setColorAt(k, this.col.copy(mixC[j]).multiplyScalar(dim)); owners[k] = i
            y0 += seg
          }
        } else {
          m.compose(this.v.set(x, 0, z), q.identity(), this.s3.set(1, hgt, 1))
          const k = glass ? gi++ : pi++
          im.setMatrixAt(k, m); im.setColorAt(k, this.col.copy(fc).multiplyScalar(dim)); owners[k] = i
        }
      } else if (charIdx.has(i)) {
        // drawn below as a character
      } else if (showDots) {
        dpos.setXYZ(di, x, 0.25 + Math.max(0, hh) * 0.25, z)
        this.col.copy(fc).multiplyScalar(dim)
        dcol.setXYZ(di, this.col.r, this.col.g, this.col.b)
        di++
      } else if (showPawns) {
        const busy = pose === 'work' || pose === 'talk' || (!pose && (st === 2 || st === 3))
        const bob = walking ? Math.abs(Math.sin(t * 11 + i)) * 0.08 : busy ? Math.abs(Math.sin(t * 5 + i)) * 0.06 : 0
        const lie = st === 6 && !walking
        m.compose(this.v.set(x, bob, z), lie ? q.setFromAxisAngle(this.s3.set(1, 0, 0), Math.PI / 2.2) : q.identity(), this.s3.set(1, height, 1))
        this.pawnBody.setMatrixAt(si, m); this.pawnBody.setColorAt(si, this.col.copy(fc).multiplyScalar(dim).lerp(T.ground, fade * 0.75))
        m.compose(this.v.set(x, bob + (height - 1) * 0.68, z), lie ? q : q.identity(), this.s3.set(1, 1, 1))
        this.pawnHead.setMatrixAt(si, m)
        si++
      }
      // attachments: ring (severity), halo (spatial flag), bubble (talking), beam
      if (this.ring[i] && ri < MAX) {
        const pulse = this.ring[i] === 3 ? 1 + Math.sin(t * 4 + i) * 0.12 : 1
        m.compose(this.v.set(x, 0, z), q.identity(), this.s3.set(pulse * (showPlinths ? 1.5 : 1), 1, pulse * (showPlinths ? 1.5 : 1)))
        this.rings.setMatrixAt(ri, m)
        this.rings.setColorAt(ri, this.ring[i] === 3 ? T.act : this.ring[i] === 2 ? T.look : T.watch)
        ri++
      }
      if ((this.flag[i] & 3) && hi < 400) {
        m.compose(this.v.set(x, 0, z), q.identity(), this.s3.set(1, 2.2 + Math.sin(t * 2 + i) * 0.2, 1))
        this.halos.setMatrixAt(hi++, m)
      }
      if ((st === 2 || (this.flag[i] & 4)) && bi < 1500 && !showDots && !showPlinths) {
        const on = (this.flag[i] & 4) ? Math.sin(t * 9 + i) > 0 : Math.sin(t * 2.2 + i * 1.7) > 0.2
        if (on) { m.compose(this.v.set(x + 0.18, 1.05 + (height - 1) * 0.7, z), q.identity(), this.s3.setScalar(1)); this.bubbles.setMatrixAt(bi++, m) }
      }
    }
    dpos.needsUpdate = true; dcol.needsUpdate = true
    this.dots.geometry.setDrawRange(0, di)
    this.dots.visible = showDots
    this.pawnBody.count = si; this.pawnHead.count = si
    this.plinthSolid.count = pi; this.plinthGlass.count = gi
    this.rings.count = ri; this.halos.count = hi; this.bubbles.count = bi
    this.pulses.count = pu; this.glows.count = gl; this.tokens.count = tk
    for (const im of [this.pawnBody, this.pawnHead, this.plinthSolid, this.plinthGlass, this.rings, this.halos, this.bubbles, this.pulses, this.glows, this.tokens]) this.bump(im)
    this.blobs.visible = showDots && this.camera.position.distanceTo(this.controls.target) > this.st.scale * 1.2
    // beams (operator actions)
    let be = 0
    for (const r of this.st.relations) {
      if (r.t !== 'beam' || r.a >= n || be >= 400) continue
      m.compose(this.v.set(X(r.a), 0, Z(r.a)), q.identity(), this.s3.set(1, 14, 1))
      this.beams.setMatrixAt(be, m)
      this.beams.setColorAt(be, r.kind === 'stop' ? T.act : r.kind === 'pause' ? T.look : T.watch)
      be++
    }
    this.beams.count = be; this.bump(this.beams)
    this.animateModels(t)
    // characters
    const keep = new Set<string>()
    charIdx.forEach((i) => {
      const id = this.ids[i]
      keep.add(id)
      let c = this.chars.get(id)
      if (!c) {
        const by = this.spec?.render.character_by ?? 'group'
        const cast: string[] = this.spec?.render.cast?.length ? this.spec.render.cast : [...CAST]
        const pick = by === 'unit' ? cast[Math.floor(hash(id) * cast.length)] : by === 'group' ? cast[Math.floor(hash(this.st!.groups[this.grp[i]] || 'x') * cast.length)] : (this.spec?.render.character ?? 'newt')
        const tint = '#' + (famC[this.fam[i]] ?? famC[0]).getHexString()
        const made = this.spec?.models?.find((md) => md.id === pick && md.kind === 'unit')
        c = made ? makeModelCharacter(made, this.theme.night, tint, 0.9, hash(id + 's')) : makeCharacter(this.kit, pick, { tint, scale: 0.9, seed: hash(id + 's') })
        c.group.userData.unit = id
        this.charLayer.add(c.group)
        this.chars.set(id, c)
      }
      const px = c.group.position.x, pz = c.group.position.z
      const x = this.cx[i], z = this.cz[i], fade = this.cfade[i]
      const moving = Math.hypot(x - px, z - pz) > 0.004
      if (moving) c.group.rotation.y = Math.atan2(x - px, z - pz)
      c.group.position.set(x, -0.3 * fade, z)          // a faded unit sinks a little and shrinks: it is out of play
      const big = tier === 'characters' ? 1.9 : 1          // a small world: every agent is a character worth seeing
      c.group.scale.setScalar(big * (1 - 0.25 * fade) * (0.75 + Math.max(-0.15, Math.min(0.45, this.h[i] * 0.15))))
      c.update(t, { pose: (this.cpose[i] as Pose | null) ?? POSE[this.state[i]] ?? 'idle', moving })
    })
    for (const [id, c] of this.chars) if (!keep.has(id)) { c.dispose(); this.chars.delete(id) }
    if (p < 1) this.drawArcs()
  }

  /* ---------------------------------------------------------------- overlays: landmark and cohort labels */
  drawLabels() {
    if (!this.st) return
    const w = this.el.clientWidth, h = this.el.clientHeight, st = this.st
    const dist = this.camera.position.distanceTo(this.controls.target)
    const items: { x: number; z: number; y: number; text: string; cls: string; key: string; color?: string }[] = []
    const close = dist < st.scale * 1.4
    if (st.catalog) {
      for (const lm of st.landmarks.slice(0, 8)) items.push({ x: lm.x * 1.06, z: lm.z * 1.06, y: 0.4, text: lm.label.replace(/_/g, ' '), cls: 'wl-axis', key: 'l' + lm.id, color: '#' + this.theme.fam(lm.id).getHexString() })
      const order = [...this.ids.keys()].sort((a, b) => this.h[b] - this.h[a]).slice(0, close ? 60 : 30)
      for (const i of order) {
        const id = this.ids[i]
        items.push({ x: this.x1[i], z: this.z1[i], y: this.plinthHeight(this.h[i]) + 0.35, text: this.labels[id] ?? id, cls: 'wl-unit wl-tower', key: 'u' + id })
      }
    }
    if (!st.catalog) for (const c of [...st.cohorts].sort((a, b) => b.n - a.n).slice(0, close ? 14 : 6)) {
      const inferred = c.task_status === 'inferred'
      const text = c.task ? (inferred && (c.task_conf ?? 0) < 0.6 ? `probably: ${c.task}` : c.task) : c.label
      items.push({ x: c.x, z: c.z, y: 2.2, text, cls: `wl-cohort ${inferred ? 'inferred' : ''} ${c.stale ? 'stale' : ''} ${c.split ? 'split' : ''}`, key: 'c' + c.id })
    }
    // zone names sit on the ground at each zone's busiest region: they say what kind of place it is
    if (dist < st.scale * 2.2) for (const z of (st.env?.zones ?? []).slice(0, 8)) items.push({ x: z.lx, z: z.lz, y: 0.05, text: z.label, cls: 'wl-zone', key: 'z' + z.name })
    if (close && !st.catalog) for (const lm of [...st.landmarks].sort((a, b) => b.events - a.events).slice(0, 12)) {
      const made = lm.model ? this.custom[lm.model] : undefined
      items.push({ x: lm.x, z: lm.z, y: made ? made.c.height * 1.1 + 0.3 : lm.arch === 'tower' ? 3 : 1.1, text: lm.label, cls: `wl-landmark ${lm.sev ? 'sev-' + lm.sev : ''}`, key: 'l' + lm.id })
    }
    if (dist < 12 && this.chars.size) for (const [id, c] of this.chars) {
      items.push({ x: c.group.position.x, z: c.group.position.z, y: 1.5, text: this.labels[id] ?? id, cls: 'wl-unit', key: 'u' + id })
    }
    while (this.labelEls.length < items.length) { const d = document.createElement('div'); this.overlay.appendChild(d); this.labelEls.push(d) }
    const placed: [number, number][] = []
    this.labelEls.forEach((el, i) => {
      const it = items[i]
      if (!it) { el.style.display = 'none'; return }
      this.v.set(it.x, it.y, it.z).project(this.camera)
      if (this.v.z > 1) { el.style.display = 'none'; return }
      const sx = ((this.v.x + 1) / 2) * w, sy = ((1 - this.v.y) / 2) * h
      if (placed.some(([px, py]) => Math.abs(px - sx) < 230 && Math.abs(py - sy) < 36)) { el.style.display = 'none'; return }   // labels never stack
      placed.push([sx, sy])
      el.style.display = ''
      el.className = 'wl ' + it.cls
      if (el.textContent !== it.text) el.textContent = it.text
      el.style.boxShadow = it.color ? `inset 5px 0 0 ${it.color}` : ''
      el.style.transform = `translate(${((this.v.x + 1) / 2) * w}px, ${((1 - this.v.y) / 2) * h}px) translate(-50%, -100%)`
    })
  }

  /* ---------------------------------------------------------------- camera */
  /** frame what is populated (units and landmarks), not the whole possible world */
  overview(animate = true) {
    const S = this.st?.scale ?? 14
    this.follow = null
    const xs: number[] = [], zs: number[] = []
    for (let i = 0; i < this.ids.length; i++) { xs.push(this.x1[i]); zs.push(this.z1[i]) }
    for (const lm of this.st?.landmarks ?? []) { xs.push(lm.x * 1.15); zs.push(lm.z * 1.15) }   // the places are part of the scene too
    if (!xs.length) { this.goto(new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, S * 1.05, S * 1.2), animate); return }
    const q = (a: number[], p: number) => { const b = [...a].sort((x, y) => x - y); return b[Math.min(b.length - 1, Math.floor(p * b.length))] }
    const lo = this.st?.catalog ? 0 : 0.03, hi = this.st?.catalog ? 1 : 0.97     // a catalog map: frame every corner
    const x0 = q(xs, lo), x1 = q(xs, hi), z0 = q(zs, lo), z1 = q(zs, hi)
    // leave room for a panel over the right side of the stage (the legend)
    const frac = Math.min(0.45, this.insetRight / Math.max(1, this.el.clientWidth))
    const cx = (x0 + x1) / 2 + (x1 - x0 + 4) * frac * 0.55, cz = (z0 + z1) / 2
    const R = Math.max(5, Math.hypot(x1 - x0, z1 - z0) / 2 + 2) / (1 - frac * 0.7)
    this.goto(new THREE.Vector3(cx, 0, cz), new THREE.Vector3(cx, R * 1.25, cz + R * 1.55), animate)
  }
  goto(target: THREE.Vector3, pos: THREE.Vector3, animate = true) {
    if (!animate) { this.controls.target.copy(target); this.camera.position.copy(pos); this.controls.update(); return }
    this.camGoal = { target, pos }
  }
  focusXZ(x: number, z: number, dist = 9) {
    const dir = this.camera.position.clone().sub(this.controls.target).normalize()
    if (!isFinite(dir.x)) dir.set(0, 0.7, 0.7)
    dir.y = Math.max(0.45, dir.y); dir.normalize()
    this.goto(new THREE.Vector3(x, 0, z), new THREE.Vector3(x, 0, z).add(dir.multiplyScalar(dist)))
  }
  focusUnit(id: string, follow = false) {
    const i = this.ids.indexOf(id)
    if (i < 0) return false
    this.focusXZ(this.x1[i], this.z1[i], 7)
    this.follow = follow ? id : null
    return true
  }
  focusLandmark(id: string) {
    const lm = this.st?.landmarks.find((l) => l.id === id)
    if (!lm) return false
    this.focusXZ(lm.x, lm.z, 11)
    return true
  }
  focusSet(ids: string[]) {
    const idx = ids.map((u) => this.ids.indexOf(u)).filter((i) => i >= 0)
    if (!idx.length) return false
    const cx = idx.reduce((a, i) => a + this.x1[i], 0) / idx.length, cz = idx.reduce((a, i) => a + this.z1[i], 0) / idx.length
    const spread = Math.max(4, ...idx.map((i) => Math.hypot(this.x1[i] - cx, this.z1[i] - cz)))
    this.focusXZ(cx, cz, Math.min(this.st!.scale * 2, spread * 2.4 + 6))
    return true
  }

  /* ---------------------------------------------------------------- input: hover, click, box select */
  bindInput() {
    const dom = this.renderer.domElement
    dom.addEventListener('pointermove', (e) => {
      if (this.drag) { this.drawRect(e); return }
      this.pending = { x: e.clientX, y: e.clientY }
    })
    dom.addEventListener('pointerleave', () => { this.pending = null; this.ev.onHover?.(null, 0, 0) })
    dom.addEventListener('pointerdown', (e) => {
      if (e.shiftKey) { this.controls.enabled = false; this.drag = { x: e.clientX, y: e.clientY } }
      else this.drag = null
      ;(dom as any)._down = { x: e.clientX, y: e.clientY }
    }, { capture: true })   // before OrbitControls, so a shift-drag selects instead of orbiting
    dom.addEventListener('pointerup', (e) => {
      if (this.drag) { this.finishRect(e); this.controls.enabled = true; this.drag = null; return }
      const d = (dom as any)._down
      if (d && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 4) this.ev.onClick?.(this.pick(e.clientX, e.clientY))
    })
  }
  drawRect(e: PointerEvent) {
    const r = this.el.getBoundingClientRect(), d = this.drag!
    const x0 = Math.min(d.x, e.clientX) - r.left, y0 = Math.min(d.y, e.clientY) - r.top
    Object.assign(this.rect.style, { display: 'block', left: x0 + 'px', top: y0 + 'px', width: Math.abs(e.clientX - d.x) + 'px', height: Math.abs(e.clientY - d.y) + 'px' })
  }
  finishRect(e: PointerEvent) {
    this.rect.style.display = 'none'
    const r = this.el.getBoundingClientRect(), d = this.drag!
    const x0 = Math.min(d.x, e.clientX) - r.left, x1 = Math.max(d.x, e.clientX) - r.left
    const y0 = Math.min(d.y, e.clientY) - r.top, y1 = Math.max(d.y, e.clientY) - r.top
    if (x1 - x0 < 6 || y1 - y0 < 6) return
    const w = this.el.clientWidth, h = this.el.clientHeight, sel: string[] = []
    for (let i = 0; i < this.ids.length; i++) {
      this.v.set(this.x1[i], 0.5, this.z1[i]).project(this.camera)
      const sx = ((this.v.x + 1) / 2) * w, sy = ((1 - this.v.y) / 2) * h
      if (sx >= x0 && sx <= x1 && sy >= y0 && sy <= y1 && this.v.z < 1) sel.push(this.ids[i])
    }
    this.ev.onSelect?.(sel)
  }
  pick(cx: number, cy: number): { kind: 'unit' | 'landmark'; id: string; index?: number } | null {
    const r = this.renderer.domElement.getBoundingClientRect()
    const ndc = new THREE.Vector2(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1)
    this.ray.setFromCamera(ndc, this.camera)
    this.ray.params.Points = { threshold: 0.35 }
    // characters first (nearest), then instanced units, then landmarks
    const hitC = this.ray.intersectObjects(this.charLayer.children, true)[0]
    if (hitC) { let o: THREE.Object3D | null = hitC.object; while (o && !o.userData.unit) o = o.parent; if (o) return { kind: 'unit', id: o.userData.unit } }
    const layers: [THREE.Object3D, (k: number) => number][] = []
    const map = (pred: (i: number) => boolean) => { const out: number[] = []; for (let i = 0; i < this.ids.length; i++) if (pred(i)) out.push(i); return (k: number) => out[k] }
    const charSet = new Set([...this.chars.keys()])
    if (this.tier === 'plinths') {
      layers.push([this.plinthSolid, (k: number) => this.plinthOwner.solid[k]], [this.plinthGlass, (k: number) => this.plinthOwner.glass[k]])
    } else if (this.tier === 'dots') layers.push([this.dots, map((i) => !charSet.has(this.ids[i]))])
    else layers.push([this.pawnBody, map((i) => !charSet.has(this.ids[i]))])
    for (const [obj, idx] of layers) {
      const hit = this.ray.intersectObject(obj, false)[0]
      if (hit) { const k = hit.instanceId ?? hit.index; if (k != null) { const i = idx(k); if (i != null) return { kind: 'unit', id: this.ids[i], index: i } } }
    }
    const lms = this.st?.landmarks ?? []
    for (const [mid, e] of Object.entries(this.custom)) {
      if (e.c.kind !== 'landmark') continue
      for (const im of e.ims) {
        const hit = this.ray.intersectObject(im, false)[0]
        if (hit && hit.instanceId != null && e.order[hit.instanceId]) return { kind: 'landmark', id: e.order[hit.instanceId] }
      }
      void mid
    }
    const archOf = (l: WLandmark) => (l.model && this.custom[l.model] ? null : this.lmMeshes[l.arch] ? l.arch : 'kiosk')
    for (const [arch, im] of Object.entries(this.lmMeshes)) {
      const hit = this.ray.intersectObject(im, false)[0]
      if (hit && hit.instanceId != null) { const list = lms.filter((l) => archOf(l) === arch); const lm = list[hit.instanceId]; if (lm) return { kind: 'landmark', id: lm.id } }
    }
    return null
  }

  /* ---------------------------------------------------------------- loop */
  loop = () => {
    if (this.disposed) return
    this.raf = requestAnimationFrame(this.loop)
    const t = this.clock.getElapsedTime()
    if (this.camGoal) {
      this.controls.target.lerp(this.camGoal.target, 0.12)
      this.camera.position.lerp(this.camGoal.pos, 0.12)
      if (this.camera.position.distanceTo(this.camGoal.pos) < 0.05) this.camGoal = null
    }
    if (this.follow) {
      const i = this.ids.indexOf(this.follow)
      if (i >= 0) { const p = this.progress(); const x = this.x0[i] + (this.x1[i] - this.x0[i]) * p, z = this.z0[i] + (this.z1[i] - this.z0[i]) * p; const d = new THREE.Vector3(x, 0, z).sub(this.controls.target); this.controls.target.add(d.multiplyScalar(0.1)); this.camera.position.add(d) }
    }
    this.controls.update()
    this.frame(t)
    this.drawLabels()
    if (this.pending && performance.now() - this.lastHover > 60) {
      this.lastHover = performance.now()
      const p = this.pending; this.pending = null
      this.ev.onHover?.(this.pick(p.x, p.y), p.x, p.y)
    }
    this.renderer.render(this.scene, this.camera)
  }

  private themeWatch?: () => void
  /** follow the app theme however it is changed (settings, system preference) */
  watchTheme() {
    const mo = new MutationObserver(() => this.setTheme())
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const on = () => this.setTheme()
    mq.addEventListener('change', on)
    this.themeWatch = () => { mo.disconnect(); mq.removeEventListener('change', on) }
  }

  dispose() {
    this.disposed = true
    this.themeWatch?.()
    cancelAnimationFrame(this.raf)
    this.controls.dispose()
    this.chars.forEach((c) => c.dispose())
    this.scene.traverse((o) => { const m = o as THREE.Mesh; if (m.geometry) m.geometry.dispose(); const mat = (m as any).material; if (mat) (Array.isArray(mat) ? mat : [mat]).forEach((x: THREE.Material) => x.dispose()) })
    this.kit.dispose()
    this.renderer.dispose()
    this.renderer.domElement.remove()
    this.overlay.remove()
    this.rect.remove()
  }
}
