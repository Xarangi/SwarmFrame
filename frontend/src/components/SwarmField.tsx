/* The swarm field: SwarmFrame's signature, and a reading, not a decoration.
 *
 *   dots       one per agent active in the last two hours (one per k agents when there are thousands; the title says k)
 *   colour     the workstream each dot's agents mostly work in, in the dashboard's fixed palette
 *   gathering  each workstream drifts around its own moving centre, so the mix reads as flocks
 *   agitation  calm when nothing needs attention, livelier with "look", restless with "act"
 *
 * Canvas 2D, ~30 fps, paused when the tab is hidden, a single still frame with prefers-reduced-motion.
 */
import React, { useEffect, useRef } from 'react'
import { famColor } from './ui'

export interface FieldInput { families: { family: string; actors: number }[]; active: number; level: 0 | 1 | 2 }

const MAX_DOTS = 420

function resolveColour(el: HTMLElement, css: string): string {
  const m = css.match(/^var\((--[^)]+)\)$/)
  return m ? getComputedStyle(el).getPropertyValue(m[1]).trim() || '#888' : css
}

export function SwarmField({ input, className = '' }: { input: FieldInput; className?: string }) {
  const host = useRef<HTMLDivElement>(null)
  const live = useRef(input)
  live.current = input
  const total = Math.max(0, input.active)
  const per = total > MAX_DOTS ? Math.ceil(total / MAX_DOTS) : 1

  useEffect(() => {
    const el = host.current
    if (!el) return
    const canvas = document.createElement('canvas')
    el.appendChild(canvas)
    const ctx = canvas.getContext('2d')!
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let W = 0, H = 0, dpr = 1
    const resize = () => {
      dpr = Math.min(2, window.devicePixelRatio || 1)
      W = el.clientWidth; H = el.clientHeight
      canvas.width = Math.max(1, W * dpr); canvas.height = Math.max(1, H * dpr)
      canvas.style.width = W + 'px'; canvas.style.height = H + 'px'
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el)

    type P = { x: number; y: number; vx: number; vy: number; f: number }
    const t0 = performance.now()
    // each workstream circles its own slowly wandering centre, in the right two thirds of the field
    const centre = (f: number, t: number) => {
      const a = t * 0.00006 * (1 + f * 0.11) + f * 2.4
      return [W * (0.6 + 0.27 * Math.cos(a) * Math.cos(a * 0.41 + f)), H * (0.5 + 0.3 * Math.sin(a * 1.2 + f * 0.7))]
    }
    let dots: P[] = []
    let colours: string[] = []
    let key = ''
    // rebuild the population when the input changes; keep existing dots where they are
    const sync = () => {
      const { families, active } = live.current
      const fam = [...families].filter((f) => f.actors > 0).sort((a, b) => b.actors - a.actors).slice(0, 8)
      const k = JSON.stringify([fam.map((f) => [f.family, f.actors]), active])
      if (k === key) return
      key = k
      colours = (fam.length ? fam : [{ family: 'other', actors: 1 }]).map((f) => resolveColour(el, famColor(f.family)))
      const n = fam.length ? Math.max(24, Math.min(MAX_DOTS, active)) : 90
      const sum = fam.reduce((a, f) => a + f.actors, 0) || 1
      const want: number[] = []
      fam.forEach((f, i) => { for (let j = 0; j < Math.round((f.actors / sum) * n); j++) want.push(i) })
      while (want.length < n) want.push(0)
      const now = performance.now() - t0
      const gauss = () => (Math.random() + Math.random() + Math.random() - 1.5) * 0.9
      dots = want.slice(0, n).map((f, i) => {
        if (dots[i] && dots[i].f === f) return dots[i]
        const [cx, cy] = centre(f, now)
        return { x: cx + gauss() * Math.min(W, H) * 0.35, y: cy + gauss() * Math.min(W, H) * 0.3, vx: 0, vy: 0, f }
      })
    }
    sync()

    let raf = 0, last = 0
    const draw = (now: number) => {
      const t = now - t0
      const lv = live.current.level
      const speed = 0.35 + lv * 0.35
      ctx.clearRect(0, 0, W, H)
      ctx.lineCap = 'round'
      for (const p of dots) {
        const [cx, cy] = centre(p.f, t)
        const ang = Math.sin(p.x * 0.006 + t * 0.00021) * Math.cos(p.y * 0.007 - t * 0.00017) * Math.PI * 2
        const dx = cx - p.x, dy = cy - p.y, d = Math.hypot(dx, dy) + 1
        const swirl = (p.f % 2 ? 1 : -1) * speed * 0.9           // flocks turn around their centre, alternately
        const ax = Math.cos(ang) * speed * 0.45 + dx * 0.0022 + (-dy / d) * swirl
        const ay = Math.sin(ang) * speed * 0.45 + dy * 0.0022 + (dx / d) * swirl
        p.vx = p.vx * 0.86 + ax * 0.14 * 4
        p.vy = p.vy * 0.86 + ay * 0.14 * 4
        if (lv === 2) { p.vx += (Math.random() - 0.5) * 0.3; p.vy += (Math.random() - 0.5) * 0.3 }
        p.x += p.vx; p.y += p.vy
        if (p.x < -10) p.x = W + 10; if (p.x > W + 10) p.x = -10
        if (p.y < -10) p.y = H + 10; if (p.y > H + 10) p.y = -10
        ctx.strokeStyle = colours[p.f] ?? colours[0]
        ctx.globalAlpha = 0.7
        ctx.lineWidth = 1.6
        ctx.beginPath(); ctx.moveTo(p.x - p.vx * 5, p.y - p.vy * 5); ctx.lineTo(p.x, p.y); ctx.stroke()
      }
      ctx.globalAlpha = 1
    }
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop)
      if (document.hidden || now - last < 33) return
      last = now
      sync()
      draw(now)
    }
    if (reduce) { for (let i = 0; i < 120; i++) draw(t0 + i * 33); const iv = setInterval(() => { sync(); draw(performance.now()) }, 5000); return () => { clearInterval(iv); ro.disconnect(); canvas.remove() } }
    raf = requestAnimationFrame(loop)
    return () => { cancelAnimationFrame(raf); ro.disconnect(); canvas.remove() }
  }, [])

  const title = total
    ? `Each streak is ${per > 1 ? `about ${per} agents` : 'an agent'} active in the last two hours, coloured by its main workstream; it moves faster when something needs attention.`
    : 'The swarm field: it fills with the agents SwarmFrame is watching.'
  return <div ref={host} className={`swarm-field ${className}`} title={title} aria-hidden />
}

/** the field's input from a snapshot */
export function fieldFrom(s: { population: { active: number; families: { family: string; actors: number }[] }; brief?: { counts: Record<string, number>; field?: { families: { family: string; actors: number }[]; active: number } } }): FieldInput {
  const c = s.brief?.counts ?? {}
  const level = c.ACT ? 2 : c.LOOK ? 1 : 0
  if (s.brief?.field) return { ...s.brief.field, level }          // catalogs: the recent record, by method
  return { families: s.population.families, active: s.population.active, level }
}

export const DEMO_FIELD: FieldInput = {
  families: [{ family: 'code', actors: 30 }, { family: 'docs', actors: 22 }, { family: 'web', actors: 18 }, { family: 'chat', actors: 14 }, { family: 'data', actors: 12 }],
  active: 160, level: 0,
}

export default React.memo(SwarmField)
