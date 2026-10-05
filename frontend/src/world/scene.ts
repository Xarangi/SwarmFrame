/* The scene a stream lives in and what its units do each window (backend/swarmscope/world/scene.py).
 *
 *   environment  ground style, zones (soft tinted discs + labels), props (library assets compiled like any model)
 *   Choreo       plays each unit's behaviour over the window's playback: walk to the place it acted on, work there,
 *                walk back; gather at a plaza; wander; scatter; follow a partner; pulse, glow, carry a token, fade.
 *
 * Positions stay measurements: every excursion starts and ends at the unit's measured position, and the server
 * decides which rule applies (first match), so this file only draws.
 */
import * as THREE from 'three'
import { tokenColour } from './models'

export interface WBehaviour { id: string; when: string; do: string; meaning: string; plan?: { do: string; dur: number }[]; params?: Record<string, number> }
export interface WZoneSpec { name: string; around: Record<string, unknown>; style: string; label: string }
export interface WPropSpec { asset: string; at: string; near?: Record<string, unknown>; count: number; meaning: string }
export interface WEnvSpec { ground: string; zones: WZoneSpec[]; props: WPropSpec[] }
export interface WSceneLegend { ground: string; zones: { name: string; label: string; style: string }[]; props: string[]; behaviours: { id: string; when: string; do: string; meaning: string }[] }
export interface WZone { name: string; label: string; style: string; discs: [number, number, number][]; lx: number; lz: number }
export interface WEnv { ground: string; zones: WZone[]; props: Record<string, number[]> }
export interface WActs { when: string; beh: string; lm: string; partner: string; n: number }

/* theme tokens for zone styles and grounds (the same tokens models use, so light and dark both work) */
export const ZONE_TOKEN: Record<string, string> = { lawn: 'leaf', paving: 'stone', tiles: 'cool', sand: 'warm', water: 'water', wood: 'wood', dark: 'shadow', plain: 'paper' }
const GROUND: Record<string, { tok: string; k: number; grid: 'polar' | 'tiles' | 'none'; gridAlpha: number }> = {
  paper: { tok: 'paper', k: 0, grid: 'polar', gridAlpha: 0.7 },
  grass: { tok: 'leaf', k: 0.3, grid: 'none', gridAlpha: 0 },
  stone: { tok: 'stone', k: 0.38, grid: 'tiles', gridAlpha: 0.25 },
  plaza_tiles: { tok: 'stone', k: 0.25, grid: 'tiles', gridAlpha: 0.55 },
  grid: { tok: 'cool', k: 0.1, grid: 'tiles', gridAlpha: 0.75 },
  water_edge: { tok: 'warm', k: 0.18, grid: 'none', gridAlpha: 0 },
  sand: { tok: 'warm', k: 0.38, grid: 'polar', gridAlpha: 0.3 },
}
export function groundLook(style: string | undefined, base: THREE.Color, night: boolean) {
  const g = GROUND[style ?? 'paper'] ?? GROUND.paper
  return { colour: base.clone().lerp(tokenColour(g.tok, night), g.k), grid: g.grid, gridAlpha: g.gridAlpha, water: style === 'water_edge' }
}
export function zoneColour(style: string, ground: THREE.Color, night: boolean) {
  return tokenColour(ZONE_TOKEN[style] ?? 'stone', night).lerp(ground, night ? 0.2 : 0.15)
}
/** a CSS colour for a zone swatch in the legend */
export function zoneSwatch(style: string) {
  const css = getComputedStyle(document.documentElement)
  const bg = new THREE.Color(css.getPropertyValue('--bg').trim() || '#f4efe6')
  const night = bg.getHSL({ h: 0, s: 0, l: 0 }).l < 0.3
  return '#' + zoneColour(style, new THREE.Color(css.getPropertyValue('--surface').trim() || '#fbf9f5'), night).getHexString()
}

/** a soft round alpha map: zones read as regions, not hard discs */
export function softDisc(): THREE.Texture {
  const c = document.createElement('canvas'); c.width = c.height = 64
  const g = c.getContext('2d')!
  const grd = g.createRadialGradient(32, 32, 4, 32, 32, 32)
  grd.addColorStop(0, '#fff'); grd.addColorStop(0.62, '#fff'); grd.addColorStop(1, '#000')
  g.fillStyle = grd; g.fillRect(0, 0, 64, 64)
  const t = new THREE.CanvasTexture(c)
  return t
}

/** square tile lines in unit space, clipped to the unit circle (scaled with the ground) */
export function tileLines(div = 28): THREE.BufferGeometry {
  const p: number[] = []
  for (let k = 0; k <= div; k++) {
    const v = -1 + (2 * k) / div, h = Math.sqrt(Math.max(0, 1 - v * v))
    if (h < 0.02) continue
    p.push(v, 0.012, -h, v, 0.012, h, -h, 0.012, v, h, 0.012, v)
  }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(p, 3))
  return g
}

export function decodeActs(a: WActs | undefined) {
  const b = (s: string) => { const r = atob(s), u = new Uint8Array(r.length); for (let i = 0; i < r.length; i++) u[i] = r.charCodeAt(i); return u.buffer }
  if (!a) return null
  return { when: new Uint16Array(b(a.when)), beh: new Uint8Array(b(a.beh)), lm: new Int16Array(b(a.lm)), partner: new Int32Array(b(a.partner)) }
}

/** how many units each behaviour moves this window (for the legend) */
export function behaviourCounts(a: WActs | undefined, n: number): number[] {
  const d = decodeActs(a), out = new Array(n).fill(0)
  if (d) for (const k of d.beh) if (k < n) out[k]++
  return out
}

/* ------------------------------------------------------------------ choreography */
const MOVES = new Set(['go_to', 'gather', 'follow', 'scatter', 'wander', 'return'])
const POSE_OF: Record<string, string> = { work: 'work', talk: 'talk', wait: 'wait' }
const BIT_REUSED = 1 << 10                // WHEN order in scene.py: ..., environment_hit (9), reused_content (10)
const hash = (s: string) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) } return (h >>> 0) / 4294967296 }
const smooth = (x: number) => x * x * (3 - 2 * x)

/* a target: home (the measured position, which itself tweens), an absolute point, or an offset from home */
interface Tgt { k: 0 | 1 | 2; x: number; z: number }
interface Seg { t0: number; t1: number; verb: string; a: Tgt; b: Tgt }
interface Plan { segs: Seg[]; carry?: { from: Tgt; to: Tgt; t0: number; t1: number } }
export interface Act { x: number; z: number; moving: boolean; pose: string | null; pulse: number; glow: number; fade: number; carry: THREE.Vector3 | null }

const HOME: Tgt = { k: 0, x: 0, z: 0 }
export interface ChoreoInput {
  ids: string[]; hx: Float32Array; hz: Float32Array; acts: WActs | undefined; behaviours: WBehaviour[]
  landmarks: { x: number; z: number; arch: string }[]; centre: (i: number) => [number, number]
}

export class Choreo {
  plans: (Plan | null)[] = []
  start = 0
  span = 4000                                    // ms of playback the excursions spread over (follows the window rate)
  active = 0

  build(c: ChoreoInput, start: number, span: number) {
    this.start = start; this.span = span
    const d = decodeActs(c.acts)
    const n = c.ids.length
    this.plans = new Array(n).fill(null)
    this.active = 0
    if (!d || d.beh.length !== n || !c.behaviours.length) return
    const plazas = c.landmarks.filter((l) => l.arch === 'plaza')
    for (let i = 0; i < n; i++) {
      const bi = d.beh[i]
      const b = bi < c.behaviours.length ? c.behaviours[bi] : null
      if (!b?.plan?.length) continue
      const hx = c.hx[i], hz = c.hz[i], id = c.ids[i]
      const reach = b.params?.reach ?? 1, radius = b.params?.radius ?? (b.do === 'scatter' ? 1.6 : 0.6)
      const lm = d.lm[i] >= 0 ? c.landmarks[d.lm[i]] : null
      const pj = d.partner[i]
      const ang = hash(id) * Math.PI * 2
      // stand at the edge of a place, on the side facing home, spread so a crowd is a ring around it
      const at = (x: number, z: number, r: number): Tgt => {
        const dx = hx - x, dz = hz - z, dl = Math.hypot(dx, dz) || 1
        const a = Math.atan2(dz / dl, dx / dl) + (hash(id + 'a') - 0.5) * 1.6
        const fx = x + Math.cos(a) * r, fz = z + Math.sin(a) * r
        return { k: 1, x: hx + (fx - hx) * reach, z: hz + (fz - hz) * reach }
      }
      const s0 = hash(id + 't') * 0.12, scale = 0.86
      const segs: Seg[] = []
      let cur: Tgt = HOME, t = s0
      let plan: Plan | null = { segs }
      for (const st of b.plan) {
        const t1 = t + st.dur * scale
        let to: Tgt | null = null
        if (st.do === 'go_to') to = lm ? at(lm.x, lm.z, 0.95) : null
        else if (st.do === 'gather') {
          let best: { x: number; z: number } | null = null, bd = Infinity
          for (const p of plazas) { const dd = (p.x - hx) ** 2 + (p.z - hz) ** 2; if (dd < bd) { bd = dd; best = p } }
          const p = best ?? lm
          to = p ? at(p.x, p.z, 1.15) : null
        } else if (st.do === 'follow') to = pj >= 0 && pj < n ? at(c.hx[pj], c.hz[pj], 0.55) : null
        else if (st.do === 'scatter') {
          const [px, pz] = lm ? [lm.x, lm.z] : c.centre(i)
          let dx = hx - px, dz = hz - pz
          const dl = Math.hypot(dx, dz)
          if (dl < 1e-3) { dx = Math.cos(ang); dz = Math.sin(ang) } else { dx /= dl; dz /= dl }
          to = { k: 2, x: dx * radius, z: dz * radius }
        } else if (st.do === 'return') to = HOME
        if (st.do === 'wander') {
          // a small loop of three legs around home, ending at home
          const pts: Tgt[] = [0, 1, 2].map((k) => { const a = ang + k * 2.1, r = radius * (0.5 + 0.5 * hash(id + k)); return { k: 2 as const, x: Math.cos(a) * r, z: Math.sin(a) * r } })
          const legs = [...pts, HOME], dt = (t1 - t) / legs.length
          legs.forEach((p, k) => { segs.push({ t0: t + k * dt, t1: t + (k + 1) * dt, verb: 'wander', a: cur, b: p }); cur = p })
        } else if (MOVES.has(st.do)) {
          if (to) { segs.push({ t0: t, t1, verb: st.do, a: cur, b: to }); cur = to }
          else segs.push({ t0: t, t1, verb: 'wait', a: cur, b: cur })
        } else {
          segs.push({ t0: t, t1, verb: st.do, a: cur, b: cur })
          if (st.do === 'carry') {
            const reused = (d.when[i] & BIT_REUSED) !== 0 && pj >= 0 && pj < n
            const from: Tgt | null = reused ? { k: 1, x: c.hx[pj], z: c.hz[pj] } : HOME
            const dest: Tgt | null = reused ? HOME : lm ? { k: 1, x: lm.x, z: lm.z } : null
            if (from && dest) plan.carry = { from, to: dest, t0: t, t1 }
          }
        }
        t = t1
      }
      if (cur !== HOME && cur.k !== 0) segs.push({ t0: t, t1: Math.min(1, t + 0.1), verb: 'return', a: cur, b: HOME })
      if (!segs.length && !plan.carry) plan = null
      this.plans[i] = plan
      if (plan) this.active++
    }
  }

  /** where unit i is now, given its (tweening) measured position; false when it is simply at home */
  at(i: number, now: number, hx: number, hz: number, out: Act): boolean {
    const p = this.plans[i]
    if (!p) return false
    const u = (now - this.start) / this.span
    out.x = hx; out.z = hz; out.moving = false; out.pose = null; out.pulse = 0; out.glow = 0; out.fade = 0; out.carry = null
    const res = (g: Tgt, o: [number, number]) => { if (g.k === 0) { o[0] = hx; o[1] = hz } else if (g.k === 1) { o[0] = g.x; o[1] = g.z } else { o[0] = hx + g.x; o[1] = hz + g.z } return o }
    const A: [number, number] = [0, 0], B: [number, number] = [0, 0]
    let any = false
    for (const s of p.segs) {
      if (u < s.t0 || u > s.t1) continue
      const f = (u - s.t0) / Math.max(1e-6, s.t1 - s.t0)
      res(s.a, A); res(s.b, B)
      const e = smooth(f)
      out.x = A[0] + (B[0] - A[0]) * e; out.z = A[1] + (B[1] - A[1]) * e
      out.moving = MOVES.has(s.verb) && Math.hypot(B[0] - A[0], B[1] - A[1]) > 0.05 && f > 0.02 && f < 0.98
      out.pose = POSE_OF[s.verb] ?? null
      const ramp = Math.min(1, f * 5, (1 - f) * 5)
      if (s.verb === 'pulse') out.pulse = (f * 3) % 1 + 1e-3
      if (s.verb === 'glow') out.glow = ramp
      if (s.verb === 'fade') out.fade = Math.min(1, f * 5)
      any = true
      break
    }
    const first = p.segs[0], last = p.segs[p.segs.length - 1]
    if (!any && ((last?.verb === 'fade' && u > last.t1) || (first?.verb === 'fade' && u < first.t0))) { out.fade = 1; any = true }   // stays faded
    if (p.carry && u >= p.carry.t0 && u <= p.carry.t1) {
      const f = smooth((u - p.carry.t0) / (p.carry.t1 - p.carry.t0))
      res(p.carry.from, A); res(p.carry.to, B)
      out.carry = new THREE.Vector3(A[0] + (B[0] - A[0]) * f, 0.6 + Math.sin(f * Math.PI) * 1.4, A[1] + (B[1] - A[1]) * f)
      any = true
    }
    return any
  }
}
