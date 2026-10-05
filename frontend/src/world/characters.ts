/* The cast: the small agent characters, ported from Newts' Lab (dashboard/static/world3d/newt.js and
 * characters.js). Each is a soft, toy-like figure built from primitives, with one shared pose animator.
 *
 *   const c = makeCharacter(kit, 'fox', { tint: '#cc5a2e', scale: 0.9 })
 *   scene.add(c.group); c.update(t, { pose: 'work', moving: false })
 *
 * In the World the TINT is the unit's workstream colour (the encoding), so the family colour of each character
 * (scarf, spots, tufts, gills) carries data; everything else about the character is identity, never data.
 * Characters cost ~30 meshes each, so the World draws them only for small populations or near the camera.
 */
import * as THREE from 'three'

export type Pose = 'idle' | 'work' | 'walk' | 'wait' | 'sleep' | 'fail' | 'carry' | 'talk'
export interface Character { group: THREE.Group; update: (t: number, s: { pose?: Pose; moving?: boolean }) => void; head: THREE.Object3D; dispose: () => void }
export const CAST = ['newt', 'human', 'frog', 'owl', 'fox', 'robot'] as const
export type CastId = (typeof CAST)[number]

/* ------------------------------------------------------------------ the kit: cached materials and meshes */
export interface Kit { night: boolean; mat: (c: string, o?: MatOpts) => THREE.MeshStandardMaterial; mesh: (g: THREE.BufferGeometry, m: THREE.Material, x?: number, y?: number, z?: number) => THREE.Mesh; dispose: () => void }
interface MatOpts { smooth?: boolean; rough?: number; metal?: number; glow?: string | null; gi?: number; vc?: boolean; alpha?: number }

export function makeKit(night: boolean): Kit {
  const cache = new Map<string, THREE.MeshStandardMaterial>()
  const mat = (c: string, o: MatOpts = {}) => {
    const key = c + '|' + JSON.stringify(o)
    let m = cache.get(key)
    if (!m) {
      m = new THREE.MeshStandardMaterial({
        color: c, roughness: o.rough ?? 0.82, metalness: o.metal ?? 0, flatShading: !o.smooth,
        emissive: o.glow ? new THREE.Color(o.glow) : new THREE.Color(0x000000), emissiveIntensity: o.glow ? (o.gi ?? (night ? 1.1 : 0.25)) : 0,
        transparent: o.alpha != null, opacity: o.alpha ?? 1, vertexColors: !!o.vc,
      })
      cache.set(key, m)
    }
    return m
  }
  const mesh = (g: THREE.BufferGeometry, m: THREE.Material, x = 0, y = 0, z = 0) => { const me = new THREE.Mesh(g, m); me.position.set(x, y, z); return me }
  return { night, mat, mesh, dispose: () => { cache.forEach((m) => m.dispose()); cache.clear() } }
}

const GEO = new Map<string, THREE.BufferGeometry>()
const geo = (key: string, make: () => THREE.BufferGeometry) => { let g = GEO.get(key); if (!g) { g = make(); GEO.set(key, g) } return g }

function tools(K: Kit, tint: string) {
  const T = {
    fam: tint,
    sph: (r: number, w = 14, h = 10) => geo(`s${r}|${w}|${h}`, () => new THREE.SphereGeometry(r, w, h)),
    cap: (r: number, l: number) => geo(`c${r}|${l}`, () => new THREE.CapsuleGeometry(r, l, 4, 8)),
    cone: (r: number, h: number, s = 8) => geo(`k${r}|${h}|${s}`, () => new THREE.ConeGeometry(r, h, s)),
    cyl: (rt: number, rb: number, h: number, s = 12) => geo(`y${rt}|${rb}|${h}|${s}`, () => new THREE.CylinderGeometry(rt, rb, h, s)),
    box: (w: number, h: number, d: number) => geo(`b${w}|${h}|${d}`, () => new THREE.BoxGeometry(w, h, d)),
    torus: (r: number, t: number, arc = 0) => geo(`t${r}|${t}|${arc}`, () => new THREE.TorusGeometry(r, t, 6, 16, arc || Math.PI * 2)),
    lathe: (name: string, prof: [number, number][]) => geo('l' + name, () => new THREE.LatheGeometry(prof.map(([r, y]) => new THREE.Vector2(r, y)), 18)),
    mat: (c: string, extra: MatOpts = {}) => K.mat(c, { smooth: true, rough: 0.7, ...extra }),
    famMat: (gid?: number, gn?: number) => K.mat(tint, { smooth: true, rough: 0.6, glow: tint, gi: K.night ? (gn ?? 0.55) : (gid ?? 0.12) }),
    dark: K.mat('#151517', { smooth: true, rough: 0.3 }),
    hl: K.mat('#ffffff', { smooth: true, glow: '#ffffff', gi: 0.6 }),
    blush: K.mat('#f4a3a8', { smooth: true, rough: 0.9 }),
    add(parent: THREE.Object3D, g: THREE.BufferGeometry, m: THREE.Material, x = 0, y = 0, z = 0, sx?: number, sy?: number, sz?: number) {
      const me = K.mesh(g, m, x, y, z)
      if (sx != null) me.scale.set(sx, sy ?? sx, sz ?? sx)
      parent.add(me); return me
    },
    eyes(parent: THREE.Object3D, dx: number, y: number, z: number, r: number) {
      return [-1, 1].map((s) => { const e = T.add(parent, T.sph(r, 12, 10), T.dark, s * dx, y, z); T.add(e, T.sph(r * 0.28, 6, 6), T.hl, r * 0.3, r * 0.35, r * 0.85); return e })
    },
    arm(parent: THREE.Object3D, s: number, x: number, y: number, z: number) { const a = new THREE.Group(); a.position.set(s * x, y, z); parent.add(a); return a },
  }
  return T
}

interface Rig { body: THREE.Group; head: THREE.Group; legs: THREE.Object3D[]; arms: THREE.Object3D[]; eyes: THREE.Object3D[]; legY: number; armRest?: number; armSpread?: number; extra?: (tt: number, pose: Pose, moving: boolean) => void }

/** the shared animation: the newt's poses, for any rig */
function animator(R: Rig, seed: number) {
  const phase = seed * 10, rest = R.armRest ?? -0.55, spread = R.armSpread ?? 0.18
  R.eyes.forEach((e) => { e.userData.sy = e.scale.y })
  return (t: number, s: { pose?: Pose; moving?: boolean }) => {
    const pose = s.pose || 'idle', moving = !!s.moving, tt = t + phase
    let bob = Math.sin(tt * 2) * 0.008, lean = 0, headTilt = 0, headTurn = 0, armL = rest, armR = rest
    let raise = [0, 0], blink = Math.sin(tt * 0.7) > 0.985
    R.legs.forEach((l) => { l.position.y = R.legY; l.rotation.x = 0 })
    if (moving || pose === 'walk' || pose === 'carry') {
      const w = Math.sin(tt * 9); bob = Math.abs(w) * 0.04; R.legs[0].rotation.x = w * 0.5; R.legs[1].rotation.x = -w * 0.5; lean = 0.08
      armL = rest + w * 0.35; armR = rest - w * 0.35
    }
    if (pose === 'idle') headTurn = Math.sin(tt * 0.45) * 0.35 * Math.max(0, Math.sin(tt * 0.21))
    if (pose === 'work') { lean = 0.12; armL = -1.1 + Math.max(0, Math.sin(tt * 11)) * 0.28; armR = -1.1 + Math.max(0, Math.sin(tt * 11 + 2)) * 0.28; headTilt = 0.14 + Math.sin(tt * 1.3) * 0.05 }
    if (pose === 'talk') { armR = -0.9 + Math.sin(tt * 4) * 0.4; headTilt = -0.05 + Math.sin(tt * 6) * 0.05; bob = Math.abs(Math.sin(tt * 3)) * 0.015 }
    if (pose === 'wait') { armR = -0.15; raise = [0, 2.55 + Math.sin(tt * 6) * 0.3]; bob = Math.abs(Math.sin(tt * 3)) * 0.035; headTilt = -0.15; headTurn = 0.12 }
    if (pose === 'carry') { armL = armR = -0.3; raise = [2.35, 2.35] }
    if (pose === 'sleep') { headTilt = 0.38; blink = true; bob = Math.sin(tt * 1.1) * 0.014 - 0.01; armL = armR = -0.15 }
    if (pose === 'fail') { headTilt = 0.5; lean = 0.2; armL = armR = -0.05; bob = -0.02; headTurn = Math.sin(tt * 0.5) * 0.08 }
    R.body.position.y = bob; R.body.rotation.x = lean
    R.head.rotation.x = headTilt; R.head.rotation.y = headTurn; R.head.rotation.z = pose === 'idle' ? Math.sin(tt * 0.6) * 0.06 : pose === 'wait' ? 0.1 : 0
    R.arms[0].rotation.x = armL; R.arms[1].rotation.x = armR
    R.arms[0].rotation.z = -spread - raise[0]; R.arms[1].rotation.z = spread + raise[1]
    R.eyes.forEach((e) => { e.scale.y = blink ? e.userData.sy * 0.15 : e.userData.sy })
    if (R.extra) R.extra(tt, pose, moving)
  }
}

function finish(root: THREE.Group, scale: number, R: Rig, seed: number): Character {
  root.scale.setScalar(scale)
  const update = animator(R, seed); update(0, {})
  return { group: root, update, head: R.head, dispose: () => root.removeFromParent() }
}
const legsPair = (T: ReturnType<typeof tools>, body: THREE.Object3D, g: THREE.BufferGeometry, m: THREE.Material, dx: number, y: number) =>
  [-1, 1].map((s) => T.add(body, g, m, s * dx, y, 0.02))

/* ------------------------------------------------------------------ the newt (axolotl) */
function lerpColor(cs: string[], u: number) {
  const n = cs.length - 1, i = Math.min(n - 1, Math.floor(u * n)), f = u * n - i
  return new THREE.Color(cs[i]).lerp(new THREE.Color(cs[i + 1]), f)
}
function taperedTube(K: Kit, pts: number[][], r0: number, r1: number, colors: string[]) {
  const curve = new THREE.CatmullRomCurve3(pts.map((p) => new THREE.Vector3(p[0], p[1], p[2])))
  const segs = 28, radial = 10, g = new THREE.TubeGeometry(curve, segs, 1, radial, false)
  const pos = g.attributes.position as THREE.BufferAttribute, cols = new Float32Array(pos.count * 3), c = new THREE.Vector3(), v = new THREE.Vector3()
  for (let i = 0; i <= segs; i++) {
    const u = i / segs, r = r0 + (r1 - r0) * Math.pow(u, 0.85), col = lerpColor(colors, u)
    curve.getPointAt(u, c)
    for (let j = 0; j <= radial; j++) {
      const k = i * (radial + 1) + j
      v.fromBufferAttribute(pos, k).sub(c).multiplyScalar(r).add(c); pos.setXYZ(k, v.x, v.y, v.z)
      cols[k * 3] = col.r; cols[k * 3 + 1] = col.g; cols[k * 3 + 2] = col.b
    }
  }
  g.setAttribute('color', new THREE.BufferAttribute(cols, 3)); g.computeVertexNormals()
  return K.mesh(g, K.mat('#ffffff', { vc: true, smooth: true }))
}
function newt(K: Kit, tint: string, scale: number, seed: number): Character {
  const T = tools(K, tint)
  const root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group()
  const shade = (d: number) => '#' + new THREE.Color(tint).offsetHSL(d, -0.05, 0.12).getHexString()
  const gill = [shade(0), shade(0.06), shade(0.12)], tail = [shade(0), shade(0.05), shade(0.1)]
  const skin = T.mat('#f1e4da'), dark = T.dark
  root.add(body)
  const legs = [-1, 1].map((s) => T.add(body, T.cap(0.06, 0.1), skin, s * 0.11, 0.1, 0.02))
  T.add(body, T.lathe('newt', [[0.001, 0.07], [0.15, 0.09], [0.205, 0.2], [0.215, 0.34], [0.19, 0.5], [0.15, 0.64], [0.12, 0.74], [0.001, 0.76]]), skin)
  const arms = [-1, 1].map((s) => {
    const a = new THREE.Group(); a.position.set(s * 0.15, 0.55, 0.09)
    T.add(a, T.cap(0.042, 0.13), skin, 0, -0.08, 0)
    a.rotation.x = -0.55; a.rotation.z = s * 0.18; body.add(a); return a
  })
  head.position.set(0, 0.9, 0); body.add(head)
  T.add(head, T.sph(0.26, 22, 16), skin, 0, 0, 0, 1.16, 0.95, 1.05)
  const eyes = [-1, 1].map((s) => { const e = T.add(head, T.sph(0.034, 12, 10), dark, s * 0.16, -0.02, 0.243); T.add(e, T.sph(0.009, 6, 6), T.hl, 0.01, 0.012, 0.03); return e })
  T.add(head, T.box(0.05, 0.006, 0.01), dark, 0, -0.085, 0.262)
  const gills = [-1, 1].map((s) => {
    const g = new THREE.Group(); g.position.set(s * 0.25, 0.02, -0.05); g.scale.setScalar(1.5)
    ;([[0.32, 0.35, gill[0]], [0.27, 0.9, gill[1]], [0.22, 1.45, gill[2]]] as [number, number, string][]).forEach(([len, ang, c]) => {
      const f = new THREE.Group(), m = K.mat(c, { smooth: true, glow: c, gi: K.night ? 0.55 : 0.12 })
      f.add(K.mesh(T.cone(0.032, len, 7), m, 0, len / 2, 0))
      for (let i = 0; i < 3; i++) {
        const y = len * (0.3 + i * 0.22), side = i % 2 ? 1 : -1, tw = K.mesh(T.cone(0.016, len * 0.38, 6), m)
        tw.position.set(side * 0.03, y + len * 0.12, 0); tw.rotation.z = -side * 0.95; f.add(tw)
      }
      f.rotation.z = -s * ang; f.rotation.x = -0.25; g.add(f)
    })
    head.add(g); return g
  })
  const tailG = new THREE.Group(); tailG.position.set(0, 0.14, -0.14); body.add(tailG)
  tailG.add(taperedTube(K, [[0, 0.02, 0], [0, -0.02, -0.2], [0.04, 0.03, -0.4], [0.09, 0.17, -0.5], [0.08, 0.3, -0.44]], 0.12, 0.025, tail))
  return finish(root, scale, {
    body, head, legs, arms, eyes, legY: 0.1,
    extra(tt, _pose, moving) {
      gills.forEach((g, i) => { g.rotation.z = (i ? -1 : 1) * Math.sin(tt * 2.2) * 0.07 })
      tailG.rotation.y = Math.sin(tt * (moving ? 6 : 1.6)) * (moving ? 0.35 : 0.15)
    },
  }, seed)
}

/* ------------------------------------------------------------------ the scientist */
function human(K: Kit, tint: string, scale: number, seed: number): Character {
  const T = tools(K, tint), root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group()
  root.add(body)
  const skin = T.mat('#f2c6a2'), coat = T.mat('#ffffff', { rough: 0.8 }), trousers = T.mat('#3d4a63'), shoe = T.mat('#5a3a2a'), hairM = T.mat('#5b3b26', { rough: 0.9 }), fam = T.famMat()
  const legs = legsPair(T, body, T.cap(0.055, 0.1), trousers, 0.085, 0.11)
  legs.forEach((l) => T.add(l, T.sph(0.066, 12, 8), shoe, 0, -0.085, 0.035, 1, 0.55, 1.45))
  T.add(body, T.lathe('coat', [[0.001, 0.1], [0.19, 0.1], [0.205, 0.18], [0.185, 0.38], [0.16, 0.55], [0.12, 0.67], [0.001, 0.72]]), coat)
  const ring = T.add(body, T.torus(0.11, 0.042), fam, 0, 0.665, 0); ring.rotation.x = Math.PI / 2
  const end = T.add(body, T.box(0.075, 0.2, 0.04), fam, 0.07, 0.54, 0.16); end.rotation.set(-0.2, 0, 0.12)
  const arms = [-1, 1].map((s) => { const a = T.arm(body, s, 0.155, 0.58, 0.05); T.add(a, T.cap(0.046, 0.14), coat, 0, -0.08, 0); T.add(a, T.sph(0.048, 10, 8), skin, 0, -0.19, 0); return a })
  head.position.set(0, 0.95, 0); body.add(head)
  T.add(head, T.sph(0.22, 20, 14), skin, 0, 0, 0, 1.06, 0.98, 1)
  const cap = T.add(head, geo('hairCap', () => new THREE.SphereGeometry(0.236, 20, 10, 0, Math.PI * 2, 0, Math.PI * 0.56)), hairM, 0, 0, -0.005, 1.07, 1, 1.06); cap.rotation.x = -0.55
  const eyes = T.eyes(head, 0.078, 0, 0.2, 0.03)
  const rim = T.mat('#2d2a26', { rough: 0.4 });
  [-1, 1].forEach((s) => T.add(head, T.torus(0.052, 0.009), rim, s * 0.078, 0, 0.222))
  T.add(head, T.box(0.05, 0.01, 0.01), rim, 0, 0.012, 0.228)
  const smile = T.add(head, T.torus(0.035, 0.007, Math.PI), T.dark, 0, -0.085, 0.205); smile.rotation.z = Math.PI
  return finish(root, scale, { body, head, legs, arms, eyes, legY: 0.11 }, seed)
}

/* ------------------------------------------------------------------ the frog */
function frog(K: Kit, tint: string, scale: number, seed: number): Character {
  const T = tools(K, tint), root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group()
  root.add(body)
  const green = T.mat('#86c46c'), belly = T.mat('#eef2cf'), fam = T.famMat()
  const legs = legsPair(T, body, T.cap(0.07, 0.06), green, 0.12, 0.1)
  legs.forEach((l) => T.add(l, T.sph(0.075, 12, 8), fam, 0, -0.085, 0.06, 1.15, 0.35, 1.45))
  T.add(body, T.lathe('frog', [[0.001, 0.07], [0.17, 0.09], [0.235, 0.2], [0.235, 0.34], [0.2, 0.48], [0.15, 0.6], [0.001, 0.66]]), green)
  T.add(body, T.sph(0.17, 14, 10), belly, 0, 0.32, 0.12, 1, 1.15, 0.6)
  ;[[0.09, 0.48, -0.16], [-0.1, 0.34, -0.2], [0.11, 0.25, -0.2], [-0.19, 0.28, 0.06], [0.2, 0.36, 0]].forEach(([x, y, z]) => T.add(body, T.sph(0.06, 10, 8), fam, x, y, z, 1, 1, 0.45))
  const arms = [-1, 1].map((s) => { const a = T.arm(body, s, 0.19, 0.5, 0.07); T.add(a, T.cap(0.045, 0.12), green, 0, -0.08, 0); T.add(a, T.sph(0.05, 10, 8), fam, 0, -0.18, 0.01, 1, 0.7, 1); return a })
  head.position.set(0, 0.84, 0); body.add(head)
  T.add(head, T.sph(0.27, 20, 14), green, 0, 0, 0, 1.2, 0.78, 1)
  const eyes = [-1, 1].map((s) => { const bulb = T.add(head, T.sph(0.1, 14, 10), green, s * 0.16, 0.15, 0.06); const e = T.add(bulb, T.sph(0.058, 12, 10), T.dark, 0, 0.015, 0.06); T.add(e, T.sph(0.016, 6, 6), T.hl, 0.018, 0.02, 0.05); return e })
  const smile = T.add(head, T.torus(0.12, 0.008, Math.PI), T.dark, 0, -0.005, 0.252, 1, 0.35, 1); smile.rotation.z = Math.PI
  return finish(root, scale, { body, head, legs, arms, eyes, legY: 0.1 }, seed)
}

/* ------------------------------------------------------------------ the owl */
function owl(K: Kit, tint: string, scale: number, seed: number): Character {
  const T = tools(K, tint), root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group()
  root.add(body)
  const brown = T.mat('#a97f5a', { rough: 0.85 }), wingM = T.mat('#8a6446', { rough: 0.85 }), pale = T.mat('#efdfc4'), amber = T.mat('#f0b24a'), fam = T.famMat()
  const legs = legsPair(T, body, T.cap(0.035, 0.06), amber, 0.09, 0.075)
  legs.forEach((l) => T.add(l, T.sph(0.06, 10, 8), amber, 0, -0.055, 0.04, 1.1, 0.4, 1.3))
  T.add(body, T.lathe('owl', [[0.001, 0.09], [0.17, 0.1], [0.24, 0.22], [0.25, 0.38], [0.225, 0.55], [0.17, 0.68], [0.001, 0.74]]), brown)
  T.add(body, T.sph(0.18, 14, 10), pale, 0, 0.36, 0.14, 1, 1.3, 0.55)
  const arms = [-1, 1].map((s) => { const a = T.arm(body, s, 0.215, 0.6, 0); T.add(a, T.sph(0.17, 12, 10), wingM, 0, -0.15, 0, 0.32, 1, 0.62); T.add(a, T.sph(0.1, 10, 8), fam, 0, -0.27, -0.01, 0.36, 0.85, 0.6); return a })
  head.position.set(0, 0.95, 0); body.add(head)
  T.add(head, T.sph(0.25, 20, 14), brown, 0, 0, 0, 1.15, 0.95, 1)
  ;[-1, 1].forEach((s) => T.add(head, T.sph(0.115, 14, 10), pale, s * 0.095, -0.005, 0.185, 1, 1, 0.38))
  const eyes = [-1, 1].map((s) => { const e = T.add(head, T.sph(0.062, 12, 10), amber, s * 0.095, 0, 0.215); const p = T.add(e, T.sph(0.036, 10, 8), T.dark, 0, 0, 0.038); T.add(p, T.sph(0.012, 6, 6), T.hl, 0.012, 0.014, 0.03); return e })
  const beak = T.add(head, T.cone(0.032, 0.09, 6), amber, 0, -0.075, 0.245); beak.rotation.x = Math.PI - 0.35
  const tufts = [-1, 1].map((s) => { const tf = T.add(head, T.cone(0.065, 0.17, 6), fam, s * 0.17, 0.2, -0.02); tf.rotation.z = -s * 0.55; return tf })
  return finish(root, scale, { body, head, legs, arms, eyes, legY: 0.075, armRest: -0.12, armSpread: 0.12,
    extra(tt, pose) { tufts.forEach((tf, i) => { tf.rotation.z = (i ? -1 : 1) * (0.55 + (pose === 'wait' ? Math.sin(tt * 6) * 0.12 : Math.sin(tt * 1.7) * 0.04)) }) } }, seed)
}

/* ------------------------------------------------------------------ the fox */
function fox(K: Kit, tint: string, scale: number, seed: number): Character {
  const T = tools(K, tint), root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group()
  root.add(body)
  const orange = T.mat('#e48a48'), cream = T.mat('#f7ecdc'), sock = T.mat('#4a3328'), fam = T.famMat()
  const legs = legsPair(T, body, T.cap(0.058, 0.1), sock, 0.1, 0.1)
  T.add(body, T.lathe('fox', [[0.001, 0.07], [0.15, 0.09], [0.2, 0.2], [0.21, 0.34], [0.185, 0.5], [0.145, 0.64], [0.115, 0.72], [0.001, 0.75]]), orange)
  T.add(body, T.sph(0.13, 14, 10), cream, 0, 0.4, 0.14, 1, 1.45, 0.55)
  const ring = T.add(body, T.torus(0.115, 0.042), fam, 0, 0.69, 0); ring.rotation.x = Math.PI / 2
  const end = T.add(body, T.box(0.075, 0.18, 0.04), fam, -0.08, 0.57, 0.15); end.rotation.set(-0.25, 0, -0.15)
  const arms = [-1, 1].map((s) => { const a = T.arm(body, s, 0.15, 0.56, 0.08); T.add(a, T.cap(0.043, 0.13), orange, 0, -0.08, 0); T.add(a, T.sph(0.046, 10, 8), sock, 0, -0.17, 0); return a })
  head.position.set(0, 0.96, 0); body.add(head)
  T.add(head, T.sph(0.23, 20, 14), orange, 0, 0, 0, 1.15, 0.95, 1)
  ;[-1, 1].forEach((s) => T.add(head, T.sph(0.1, 12, 8), cream, s * 0.12, -0.075, 0.13, 1, 0.75, 0.75))
  const snout = T.add(head, T.cone(0.085, 0.17, 10), cream, 0, -0.065, 0.24); snout.rotation.x = Math.PI / 2
  T.add(head, T.sph(0.03, 8, 6), T.dark, 0, -0.065, 0.325)
  const ears = [-1, 1].map((s) => { const e = T.add(head, T.cone(0.08, 0.21, 6), orange, s * 0.14, 0.2, -0.02); e.rotation.z = -s * 0.35; T.add(e, T.cone(0.034, 0.085, 6), sock, 0, 0.064, 0); return e })
  const eyes = T.eyes(head, 0.088, 0.035, 0.2, 0.032)
  const tail = new THREE.Group(); tail.position.set(0, 0.2, -0.16); body.add(tail)
  const bend = new THREE.Group(); bend.rotation.x = 0.75; tail.add(bend)
  T.add(bend, T.sph(0.13, 14, 10), orange, 0, 0, -0.2, 0.78, 0.78, 1.9)
  T.add(bend, T.sph(0.085, 12, 8), cream, 0, 0, -0.42, 1, 1, 1.3)
  return finish(root, scale, { body, head, legs, arms, eyes, legY: 0.1,
    extra(tt, pose, moving) {
      tail.rotation.y = Math.sin(tt * (moving ? 7 : pose === 'wait' ? 5 : 1.6)) * (moving || pose === 'wait' ? 0.4 : 0.15)
      bend.rotation.x = pose === 'fail' || pose === 'sleep' ? 0.2 : 0.75
      ears.forEach((e, i) => { e.rotation.z = (i ? -1 : 1) * (pose === 'fail' ? 0.9 : 0.35 + Math.max(0, Math.sin(tt * 0.9 + i)) * 0.06) })
    } }, seed)
}

/* ------------------------------------------------------------------ the robot */
function robot(K: Kit, tint: string, scale: number, seed: number): Character {
  const T = tools(K, tint), root = new THREE.Group(), body = new THREE.Group(), head = new THREE.Group()
  root.add(body)
  const shell = T.mat('#d3dcdf', { rough: 0.45, metal: 0.15 }), joint = T.mat('#8e9ba2', { rough: 0.5, metal: 0.2 }), screen = T.mat('#26353c', { rough: 0.3 })
  const famLight = T.famMat(0.45, 0.9), eyeM = K.mat('#bff6ff', { smooth: true, glow: '#8fefff', gi: K.night ? 1.0 : 0.6 })
  const legs = legsPair(T, body, T.cyl(0.05, 0.05, 0.14, 10), joint, 0.095, 0.12)
  legs.forEach((l) => T.add(l, T.box(0.12, 0.06, 0.17), shell, 0, -0.08, 0.025))
  T.add(body, T.box(0.38, 0.4, 0.3), shell, 0, 0.4, 0)
  T.add(body, T.box(0.2, 0.075, 0.02), famLight, 0, 0.29, 0.155)
  T.add(body, T.cyl(0.055, 0.065, 0.1, 10), joint, 0, 0.64, 0)
  const arms = [-1, 1].map((s) => { const a = T.arm(body, s, 0.215, 0.56, 0); T.add(a, T.sph(0.05, 10, 8), joint); T.add(a, T.cyl(0.035, 0.035, 0.2, 8), joint, 0, -0.11, 0); T.add(a, T.sph(0.055, 10, 8), shell, 0, -0.23, 0); return a })
  head.position.set(0, 0.87, 0); body.add(head)
  T.add(head, T.box(0.46, 0.33, 0.34), shell)
  T.add(head, T.box(0.37, 0.22, 0.02), screen, 0, -0.005, 0.17)
  const eyes = [-1, 1].map((s) => T.add(head, T.sph(0.038, 10, 8), eyeM, s * 0.085, 0.02, 0.18, 1, 1.35, 0.6))
  const smile = T.add(head, T.torus(0.04, 0.008, Math.PI), eyeM, 0, -0.045, 0.182); smile.rotation.z = Math.PI
  T.add(head, T.cyl(0.012, 0.012, 0.14, 6), joint, 0, 0.235, 0)
  const bulb = T.add(head, T.sph(0.045, 12, 10), famLight, 0, 0.33, 0)
  return finish(root, scale, { body, head, legs, arms, eyes, legY: 0.12,
    extra(tt, pose) {
      bulb.scale.setScalar(pose === 'wait' ? 1 + Math.abs(Math.sin(tt * 6)) * 0.5 : pose === 'sleep' || pose === 'fail' ? 0.75 : 1 + Math.sin(tt * 2.5) * 0.08)
      smile.scale.y = pose === 'fail' ? -1 : 1; smile.position.y = pose === 'fail' ? -0.07 : -0.045
    } }, seed)
}

const BUILDERS: Record<CastId, (K: Kit, tint: string, scale: number, seed: number) => Character> = { newt, human, frog, owl, fox, robot }

/** any character by id; `tint` is the unit's workstream colour; `seed` (0..1) desynchronises the animation. */
export function makeCharacter(K: Kit, id: string, o: { tint: string; scale?: number; seed?: number }): Character {
  const b = BUILDERS[(CAST as readonly string[]).includes(id) ? (id as CastId) : 'newt']
  return b(K, o.tint, o.scale ?? 1, o.seed ?? Math.random())
}
