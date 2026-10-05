/* Models the designer made for this stream (backend/swarmscope/world/models.py): a part list compiled once.
 *
 *   compile(def, theme)   -> instanced-ready meshes: static parts merged per material (vertex colours from theme
 *                            tokens; `tint` parts left white so the instance colour carries the data), animated parts
 *                            kept separate with their pivot so the frame loop can turn them
 *   buildGroup(def, ...)  -> a plain THREE.Group (previews, and custom characters)
 *   makeModelCharacter    -> a Character with the same poses as the premade cast
 *
 * Nothing here runs designer code: a model is data, validated on the server, drawn in the dashboard's own palette.
 */
import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import type { Character, Pose } from './characters'

export interface MPart { shape: string; size: any[]; at?: number[]; rot?: number[]; colour?: string; material?: string; anim?: string | null; name?: string }
export interface MDef { id: string; kind: 'landmark' | 'unit' | 'prop'; meaning: string; parts: MPart[]; by?: string }
export interface MScenery { model: string; at: 'centre' | 'rim' | 'territories'; count: number; meaning: string }

const DAY: Record<string, string> = {
  ink: '#2a2723', paper: '#fbf9f5', stone: '#d9cfbf', wood: '#c49a6c', metal: '#9aa3ab', glass: '#cfe0ea', leaf: '#8fae7e',
  water: '#7fa7c4', warm: '#e6d3b3', cool: '#8c97a6', shadow: '#8b8276', tint: '#ffffff',
}
const NIGHT: Record<string, string> = {
  ink: '#ece6dc', paper: '#2b2925', stone: '#6b645a', wood: '#8a6a4a', metal: '#7d868e', glass: '#8fb3c7', leaf: '#6f8f60',
  water: '#4f7b99', warm: '#9c8a6c', cool: '#5d6876', shadow: '#1d1b19', tint: '#ffffff',
}
export function tokenColour(tok: string | undefined, night: boolean): THREE.Color {
  if (tok === 'accent') return new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#cc5a2e')
  return new THREE.Color((night ? NIGHT : DAY)[tok ?? 'stone'] ?? (night ? NIGHT.stone : DAY.stone))
}

const D2R = Math.PI / 180

function wedge(w: number, h: number, d: number): THREE.BufferGeometry {
  const P = (x: number, y: number, z: number) => new THREE.Vector3(x, y, z)
  const L = [P(-w / 2, -h / 2, -d / 2), P(-w / 2, h / 2, -d / 2), P(-w / 2, -h / 2, d / 2)]
  const R = L.map((v) => P(w / 2, v.y, v.z))
  const c = new THREE.Vector3(0, -h / 6, -d / 6)
  const out: number[] = []
  const tri = (a: THREE.Vector3, b: THREE.Vector3, e: THREE.Vector3) => {
    const n = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(e, a))
    const mid = new THREE.Vector3().add(a).add(b).add(e).multiplyScalar(1 / 3).sub(c)
    const [p, q, r] = n.dot(mid) < 0 ? [a, e, b] : [a, b, e]
    out.push(p.x, p.y, p.z, q.x, q.y, q.z, r.x, r.y, r.z)
  }
  const quad = (a: THREE.Vector3, b: THREE.Vector3, e: THREE.Vector3, f: THREE.Vector3) => { tri(a, b, e); tri(a, e, f) }
  tri(L[0], L[1], L[2]); tri(R[0], R[1], R[2])
  quad(L[0], R[0], R[2], L[2])        // bottom
  quad(L[0], L[1], R[1], R[0])        // back
  quad(L[1], L[2], R[2], R[1])        // slope
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(out, 3))
  g.computeVertexNormals()
  return g
}

/** the part's geometry in its own frame (centred as the server documents), before `rot` and `at` */
export function partGeometry(p: MPart): THREE.BufferGeometry {
  const v: any[] = (p.size ?? []).map((x: any) => (Array.isArray(x) ? x : Number(x)))
  switch (p.shape) {
    case 'box': return new THREE.BoxGeometry(v[0], v[1], v[2])
    case 'cylinder': return new THREE.CylinderGeometry(v[0], v[1], v[2], 18)
    case 'cone': return new THREE.ConeGeometry(v[0], v[1], 18)
    case 'sphere': return new THREE.SphereGeometry(v[0], 16, 12)
    case 'dome': {
      const top = new THREE.SphereGeometry(v[0], 16, 7, 0, Math.PI * 2, 0, Math.PI / 2)
      const cap = new THREE.CircleGeometry(v[0], 16).rotateX(Math.PI / 2)
      return mergeGeometries([strip(top), strip(cap)])!
    }
    case 'capsule': return new THREE.CapsuleGeometry(v[0], v[1], 4, 12)
    case 'torus': return new THREE.TorusGeometry(v[0], v[1], 8, 28, ((v[2] ?? 360) as number) * D2R)
    case 'disc': return new THREE.CylinderGeometry(v[0], v[0], 0.02, 32)
    case 'ring': {
      const [a, b] = v as number[]
      return new THREE.LatheGeometry([new THREE.Vector2(a, -0.01), new THREE.Vector2(b, -0.01), new THREE.Vector2(b, 0.01), new THREE.Vector2(a, 0.01), new THREE.Vector2(a, -0.01)], 32)
    }
    case 'prism': return new THREE.CylinderGeometry(v[0], v[0], v[1], Math.max(3, Math.min(8, Math.round(v[2]))))
    case 'wedge': return wedge(v[0], v[1], v[2])
    case 'lathe': {
      const prof = (v.length === 1 && Array.isArray(v[0]) && Array.isArray(v[0][0]) ? v[0] : v) as number[][]
      return new THREE.LatheGeometry(prof.map(([r, y]) => new THREE.Vector2(Math.max(0, r), y)), 20)
    }
    default: return new THREE.BoxGeometry(0.2, 0.2, 0.2)
  }
}

/** keep only position and normal, non-indexed, so any two parts can be merged */
function strip(g: THREE.BufferGeometry): THREE.BufferGeometry {
  const n = g.index ? g.toNonIndexed() : g
  for (const k of Object.keys(n.attributes)) if (k !== 'position' && k !== 'normal') n.deleteAttribute(k)
  if (!n.getAttribute('normal')) n.computeVertexNormals()
  return n
}

const rotOf = (p: MPart) => new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(...((p.rot ?? [0, 0, 0]).map((x) => x * D2R) as [number, number, number]), 'XYZ'))
const atOf = (p: MPart) => new THREE.Matrix4().makeTranslation(...((p.at ?? [0, 0, 0]) as [number, number, number]))

export function materialFor(kind: string | undefined, night: boolean, opts: { vertexColors?: boolean; colour?: THREE.Color } = {}): THREE.Material {
  const base = { vertexColors: !!opts.vertexColors, color: opts.colour ?? new THREE.Color(0xffffff) }
  switch (kind) {
    case 'glow': return new THREE.MeshBasicMaterial({ ...base })      // unlit: reads as a light in both themes
    case 'glass': return new THREE.MeshStandardMaterial({ ...base, roughness: 0.1, metalness: 0, transparent: true, opacity: 0.45, depthWrite: false })
    case 'metal': return new THREE.MeshStandardMaterial({ ...base, roughness: 0.35, metalness: 0.55 })
    case 'gloss': return new THREE.MeshStandardMaterial({ ...base, roughness: 0.32 })
    default: return new THREE.MeshStandardMaterial({ ...base, roughness: 0.85 })
  }
}

export interface CompiledMesh { geo: THREE.BufferGeometry; mat: THREE.Material; tint: boolean; anim: string | null; at: THREE.Matrix4; rot: THREE.Matrix4 }
export interface Compiled { id: string; kind: string; meshes: CompiledMesh[]; height: number }

/** muted: scenery colours are pulled toward the ground so they never compete with data */
export function compile(def: MDef, night: boolean, muted = false, ground?: THREE.Color, mute = 0.35): Compiled {
  const groups = new Map<string, THREE.BufferGeometry[]>()
  const meshes: CompiledMesh[] = []
  const box = new THREE.Box3()
  for (const p of def.parts) {
    const raw = strip(partGeometry(p))
    const tint = p.colour === 'tint'
    const col = tokenColour(p.colour, night)
    if (muted && ground) col.lerp(ground, mute)
    const colours = new Float32Array(raw.getAttribute('position').count * 3)
    for (let i = 0; i < colours.length; i += 3) { colours[i] = col.r; colours[i + 1] = col.g; colours[i + 2] = col.b }
    raw.setAttribute('color', new THREE.BufferAttribute(colours, 3))
    const placed = raw.clone().applyMatrix4(new THREE.Matrix4().multiplyMatrices(atOf(p), rotOf(p)))
    placed.computeBoundingBox(); box.union(placed.boundingBox!)
    if (p.anim) {
      meshes.push({ geo: raw, mat: materialFor(p.material, night, { vertexColors: true }), tint, anim: p.anim, at: atOf(p), rot: rotOf(p) })
    } else {
      const key = `${p.material ?? 'matte'}|${tint ? 1 : 0}`
      groups.set(key, [...(groups.get(key) ?? []), placed])
    }
  }
  for (const [key, list] of groups) {
    const [mat, tint] = key.split('|')
    meshes.push({ geo: mergeGeometries(list)!, mat: materialFor(mat, night, { vertexColors: true }), tint: tint === '1', anim: null, at: new THREE.Matrix4(), rot: new THREE.Matrix4() })
  }
  return { id: def.id, kind: def.kind, meshes, height: Math.max(0.3, box.max.y) }
}

/** the animation of one part at time t, as a matrix applied between its position and its own rotation */
export function animMatrix(anim: string | null, t: number, phase: number, out: THREE.Matrix4): THREE.Matrix4 {
  if (anim === 'spin') return out.makeRotationY(t * 1.1 + phase * 6)
  if (anim === 'sway') return out.makeRotationZ(Math.sin(t * 1.6 + phase * 6) * 0.13)
  if (anim === 'bob') return out.makeTranslation(0, Math.sin(t * 2 + phase * 6) * 0.06, 0)
  return out.identity()
}

/** a plain group for one model (previews and characters); `tint` colours the tint parts */
export function buildGroup(def: MDef, night: boolean, tint = '#cc5a2e'): { group: THREE.Group; animate: (t: number) => void; dispose: () => void } {
  const group = new THREE.Group()
  const animated: { pivot: THREE.Object3D; anim: string; at: THREE.Vector3 }[] = []
  const owned: (THREE.BufferGeometry | THREE.Material)[] = []
  for (const p of def.parts) {
    const g = partGeometry(p)
    const m = materialFor(p.material, night, { colour: p.colour === 'tint' ? new THREE.Color(tint) : tokenColour(p.colour, night) })
    owned.push(g, m)
    const mesh = new THREE.Mesh(g, m)
    mesh.rotation.set(...((p.rot ?? [0, 0, 0]).map((x) => x * D2R) as [number, number, number]), 'XYZ')
    const pivot = new THREE.Object3D()
    const at = new THREE.Vector3(...((p.at ?? [0, 0, 0]) as [number, number, number]))
    pivot.position.copy(at)
    pivot.add(mesh)
    group.add(pivot)
    if (p.anim) animated.push({ pivot, anim: p.anim, at })
  }
  const phase = Math.random()
  return {
    group,
    animate: (t: number) => {
      for (const a of animated) {
        if (a.anim === 'spin') a.pivot.rotation.y = t * 1.1 + phase * 6
        else if (a.anim === 'sway') a.pivot.rotation.z = Math.sin(t * 1.6 + phase * 6) * 0.13
        else if (a.anim === 'bob') a.pivot.position.y = a.at.y + Math.sin(t * 2 + phase * 6) * 0.06
      }
    },
    dispose: () => owned.forEach((o) => o.dispose()),
  }
}

/** a custom unit model as a Character: the same poses as the premade cast, on the whole body */
export function makeModelCharacter(def: MDef, night: boolean, tint: string, scale = 1, seed = Math.random()): Character {
  const outer = new THREE.Group()
  const body = buildGroup(def, night, tint)
  outer.add(body.group)
  outer.scale.setScalar(scale)
  const top = Math.max(0.3, new THREE.Box3().setFromObject(body.group).max.y)
  const head = new THREE.Object3D()
  head.position.y = top
  outer.add(head)
  const g = body.group
  return {
    group: outer,
    head,
    update: (t: number, s: { pose?: Pose; moving?: boolean }) => {
      const tt = t + seed * 10
      const pose = s.moving ? 'walk' : s.pose ?? 'idle'
      g.position.set(0, 0, 0); g.rotation.set(0, 0, 0); g.scale.set(1, 1, 1)
      if (pose === 'idle') g.scale.y = 1 + Math.sin(tt * 2) * 0.015
      else if (pose === 'walk' || pose === 'carry') { g.position.y = Math.abs(Math.sin(tt * 10)) * 0.05; g.rotation.x = 0.08 }
      else if (pose === 'work') g.position.y = Math.abs(Math.sin(tt * 8)) * 0.03
      else if (pose === 'talk') g.rotation.y = Math.sin(tt * 6) * 0.14
      else if (pose === 'wait') g.rotation.z = Math.sin(tt * 1.5) * 0.06
      else if (pose === 'sleep') { g.rotation.x = -Math.PI / 2.2; g.position.y = 0.15 }
      else if (pose === 'fail') { g.rotation.z = 0.35 + Math.sin(tt * 30) * 0.03 }
      body.animate(tt)
    },
    dispose: body.dispose,
  }
}
