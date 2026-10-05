import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { area, curveMonotoneX, line } from 'd3-shape'
import { scaleLinear, scaleTime } from 'd3-scale'
import { useStore } from '../store'
import { famColor, fmtNum, fmtTick, fmtTime, groupColor } from '../components/ui'

export function useSize<T extends HTMLElement>(): [React.RefObject<T | null>, { w: number; h: number }] {
  const ref = useRef<T>(null)
  const [s, set] = useState({ w: 600, h: 200 })
  useLayoutEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => set({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, s]
}

const iso = (t: string) => new Date(t.endsWith('Z') ? t : t + 'Z')

/* =============================================================== stacked timeline */
export interface TimelineData {
  start: string; end: string; now: string; series: string[]
  buckets: { t: string; total: number; by: Record<string, number> }[]
  markers: { t: string; kind: string; level: string; text: string; id: string }[]
}

export function StackedTimeline({ data, height = 190 }: { data: TimelineData | null; height?: number }) {
  const [ref, { w }] = useSize<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  if (!data || !data.buckets.length) return <div ref={ref} style={{ height }} />
  const m = { l: 34, r: 10, t: 22, b: 22 }
  const x = scaleTime().domain([iso(data.start), iso(data.end)]).range([m.l, w - m.r])
  const nowX = x(iso(data.now))
  const visible = data.buckets.filter((b) => iso(b.t) <= iso(data.now))
  const stacks = data.series.map(() => [] as { x: number; y0: number; y1: number }[])
  let maxY = 1
  visible.forEach((b) => {
    let acc = 0
    data.series.forEach((s, i) => {
      const v = b.by[s] || 0
      stacks[i].push({ x: x(iso(b.t)), y0: acc, y1: acc + v })
      acc += v
    })
    maxY = Math.max(maxY, acc)
  })
  const y = scaleLinear().domain([0, maxY * 1.08]).range([height - m.b, m.t]).nice()
  const ar = area<{ x: number; y0: number; y1: number }>().x((d) => d.x).y0((d) => y(d.y0)).y1((d) => y(d.y1)).curve(curveMonotoneX)
  const ticks = x.ticks(Math.max(2, Math.floor(w / 110)))
  const hb = hover != null ? visible[hover] : null
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <svg className="chart" width={w} height={height}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
          const px = e.clientX - r.left
          if (px > nowX + 4 || !visible.length) return setHover(null)
          let best = 0
          visible.forEach((b, i) => { if (Math.abs(x(iso(b.t)) - px) < Math.abs(x(iso(visible[best].t)) - px)) best = i })
          setHover(best)
        }}
        onMouseLeave={() => setHover(null)}>
        {y.ticks(3).map((t) => (
          <g key={t}><line className="grid-line" x1={m.l} x2={w - m.r} y1={y(t)} y2={y(t)} />
            <text x={m.l - 6} y={y(t) + 3} textAnchor="end">{fmtNum(t)}</text></g>
        ))}
        <rect x={nowX} y={m.t} width={Math.max(0, w - m.r - nowX)} height={height - m.t - m.b} fill="var(--sunken)" opacity={0.6} />
        {stacks.map((s, i) => (
          <path key={data.series[i]} d={ar(s) || ''} fill={famColor(data.series[i])} fillOpacity={0.85}
            stroke="var(--surface)" strokeWidth={1.25} />
        ))}
        {data.markers.filter((mk) => iso(mk.t) <= iso(data.now)).map((mk) => {
          const mx = x(iso(mk.t))
          const c = mk.level === 'ALERT' || mk.level === 'PAGE' ? 'var(--lv-alert)' : mk.kind === 'REVISED' ? 'var(--st-self)' : 'var(--lv-investigate)'
          return <g key={mk.id}><line x1={mx} x2={mx} y1={m.t - 4} y2={height - m.b} stroke={c} strokeWidth={1} strokeDasharray="2 3" />
            <circle cx={mx} cy={m.t - 8} r={4} fill={c} stroke="var(--surface)" strokeWidth={2}><title>{mk.text}</title></circle></g>
        })}
        <line x1={nowX} x2={nowX} y1={m.t - 8} y2={height - m.b} stroke="var(--ink)" strokeWidth={1.5} />
        <text x={Math.min(nowX + 4, w - 40)} y={m.t - 10} style={{ fill: 'var(--ink)' }}>now</text>
        {ticks.map((t) => <text key={+t} x={x(t)} y={height - 6} textAnchor="middle">{fmtTick(t, +iso(data.end) - +iso(data.start))}</text>)}
        {hb && <line x1={x(iso(hb.t))} x2={x(iso(hb.t))} y1={m.t} y2={height - m.b} stroke="var(--ink-2)" strokeWidth={1} />}
      </svg>
      {hb && (
        <div className="tooltip" style={{ left: Math.min(x(iso(hb.t)) + 12, w - 200), top: 8 }}>
          <div className="mono muted">{fmtTime(hb.t, true)} · {hb.total} events</div>
          {data.series.filter((s) => hb.by[s]).sort((a, b) => (hb.by[b] || 0) - (hb.by[a] || 0)).map((s) => (
            <div key={s} className="row" style={{ justifyContent: 'space-between', gap: 14 }}>
              <span className="row" style={{ gap: 6 }}><i style={{ width: 8, height: 8, borderRadius: 2, background: famColor(s), display: 'inline-block' }} />{s}</span>
              <span className="num">{hb.by[s]}</span>
            </div>
          ))}
        </div>
      )}
      <div className="legend" style={{ marginTop: 6 }}>
        {data.series.map((s) => <span key={s}><i style={{ background: famColor(s) }} />{s}</span>)}
      </div>
    </div>
  )
}

/* =============================================================== bipartite map */
export interface GraphData {
  nodes: { id: string; kind: 'actor' | 'resource'; label: string; group: string | null; weight: number; focus: number; incident?: string | null; type?: string }[]
  edges: { source: string; target: string; weight: number; family: string | null; recent: boolean }[]
}

export function Bipartite({ data, height = 420 }: { data: GraphData | null; height?: number }) {
  const [ref, { w }] = useSize<HTMLDivElement>()
  const [hover, setHover] = useState<string | null>(null)
  const open = useStore((s) => s.openDrawer)
  const layout = useMemo(() => {
    if (!data) return null
    const actors = data.nodes.filter((n) => n.kind === 'actor').sort((a, b) => (a.group || '').localeCompare(b.group || '') || b.weight - a.weight)
    const res = data.nodes.filter((n) => n.kind === 'resource').sort((a, b) => (a.group || '').localeCompare(b.group || '') || b.weight - a.weight)
    return { actors, res }
  }, [data])
  if (!data || !layout || !data.nodes.length) return <div ref={ref} style={{ height: 120 }} />
  const rows = Math.max(layout.actors.length, layout.res.length)
  const h = Math.max(height, rows * 17 + 40)
  const colA = 150, colR = w - 170
  const yA = (i: number) => 24 + (i + 0.5) * ((h - 40) / Math.max(1, layout.actors.length))
  const yR = (i: number) => 24 + (i + 0.5) * ((h - 40) / Math.max(1, layout.res.length))
  const pos: Record<string, { x: number; y: number }> = {}
  layout.actors.forEach((n, i) => (pos[n.id] = { x: colA, y: yA(i) }))
  layout.res.forEach((n, i) => (pos[n.id] = { x: colR, y: yR(i) }))
  const maxW = Math.max(...data.edges.map((e) => e.weight), 1)
  const maxN = Math.max(...data.nodes.map((n) => n.weight), 1)
  const neighbors = new Set<string>()
  if (hover) data.edges.forEach((e) => { if (e.source === hover) neighbors.add(e.target); if (e.target === hover) neighbors.add(e.source) })
  const lit = (id: string) => !hover || id === hover || neighbors.has(id)
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <svg className="chart" width={w} height={h}>
        <text x={colA} y={12} textAnchor="end" className="label" style={{ fill: 'var(--ink-3)', letterSpacing: '.08em' }}>AGENTS</text>
        <text x={colR} y={12} className="label" style={{ fill: 'var(--ink-3)', letterSpacing: '.08em' }}>SHARED RESOURCES</text>
        {data.edges.map((e, i) => {
          const a = pos[e.source], b = pos[e.target]
          if (!a || !b) return null
          const on = !hover || e.source === hover || e.target === hover
          const mx = (a.x + b.x) / 2
          return <path key={i} d={`M${a.x + 6},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x - 6},${b.y}`} fill="none"
            stroke={famColor(e.family)} strokeOpacity={on ? (e.recent ? 0.75 : 0.32) : 0.05}
            strokeWidth={0.8 + 3.2 * Math.sqrt(e.weight / maxW)} />
        })}
        {[...layout.actors, ...layout.res].map((n) => {
          const p = pos[n.id]
          const r = 3.5 + 5 * Math.sqrt(n.weight / maxN)
          const left = n.kind === 'actor'
          const color = left ? groupColor(n.group) : famColor(n.group)
          return (
            <g key={n.id} opacity={lit(n.id) ? 1 : 0.25} style={{ cursor: 'pointer' }}
              onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}
              onClick={() => n.type !== 'group' && open({ kind: 'entity', id: n.id })}>
              {n.incident && <circle cx={p.x} cy={p.y} r={r + 7} fill="none" stroke={`var(--lv-${n.incident.toLowerCase()})`} strokeWidth={1.5} strokeDasharray="3 2" />}
              {n.focus > 0 && <circle cx={p.x} cy={p.y} r={r + 3.5} fill="none" stroke="var(--ink)" strokeWidth={1.5} />}
              <circle cx={p.x} cy={p.y} r={r} fill={color} stroke="var(--surface)" strokeWidth={2} />
              <text x={left ? p.x - r - 8 : p.x + r + 8} y={p.y + 3.5} textAnchor={left ? 'end' : 'start'}
                style={{ fill: hover === n.id ? 'var(--ink)' : 'var(--ink-2)', fontFamily: 'var(--font-ui)', fontSize: 11.5 }}>
                {n.label.length > 22 ? n.label.slice(0, 21) + '…' : n.label}
              </text>
              <rect x={left ? p.x - 140 : p.x - 8} y={p.y - 8} width={148} height={16} fill="transparent" />
            </g>
          )
        })}
      </svg>
      <div className="row" style={{ gap: 16, flexWrap: 'wrap', marginTop: 4 }}>
        <span className="mono muted">{(data as any).collapsed ? `${(data as any).actors} agents grouped by team` : 'left: agents colored by group'} · right: resources colored by workstream</span>
        <span className="mono muted" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <svg width="14" height="14"><circle cx="7" cy="7" r="5.5" fill="none" stroke="var(--ink)" strokeWidth="1.5" /></svg>SwarmFrame is looking here
          <svg width="14" height="14"><circle cx="7" cy="7" r="5.5" fill="none" stroke="var(--lv-investigate)" strokeWidth="1.5" strokeDasharray="3 2" /></svg>part of a finding
        </span>
      </div>
    </div>
  )
}

/* =============================================================== swimlanes */
export interface SwimData { since: string; now: string; bins: number; lanes: { id: string; label: string; group: string | null; total: number; cells: ({ family: string; n: number } | null)[] }[] }

export function Swimlanes({ data }: { data: SwimData | null }) {
  const [ref, { w }] = useSize<HTMLDivElement>()
  const open = useStore((s) => s.openDrawer)
  const [tip, setTip] = useState<{ x: number; y: number; t: string } | null>(null)
  if (!data) return <div ref={ref} />
  const labelW = 130
  const cw = Math.max(2, (w - labelW - 8) / data.bins)
  const max = Math.max(1, ...data.lanes.flatMap((l) => l.cells.map((c) => c?.n || 0)))
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <svg className="chart" width={w} height={data.lanes.length * 18 + 22}>
        {data.lanes.map((l, i) => (
          <g key={l.id} transform={`translate(0, ${i * 18})`}>
            <text x={labelW - 8} y={12} textAnchor="end" style={{ fontFamily: 'var(--font-ui)', fontSize: 11.5, fill: 'var(--ink-2)', cursor: 'pointer' }}
              onClick={() => open({ kind: 'entity', id: l.id })}>{l.label.length > 18 ? l.label.slice(0, 17) + '…' : l.label}</text>
            <rect x={labelW} y={3} width={w - labelW - 8} height={12} rx={3} fill="var(--sunken)" />
            {l.cells.map((c, j) => c && (
              <rect key={j} x={labelW + j * cw + 0.5} y={3} width={Math.max(1, cw - 1)} height={12} rx={2}
                fill={famColor(c.family)} opacity={0.35 + 0.65 * Math.sqrt(c.n / max)}
                onMouseEnter={() => setTip({ x: labelW + j * cw, y: i * 18, t: `${l.label} · ${c.family} · ${c.n} events` })}
                onMouseLeave={() => setTip(null)} />
            ))}
          </g>
        ))}
        <text x={labelW} y={data.lanes.length * 18 + 16}>{fmtTime(data.since, true)}</text>
        <text x={w - 8} y={data.lanes.length * 18 + 16} textAnchor="end">{fmtTime(data.now, true)}</text>
      </svg>
      {tip && <div className="tooltip" style={{ left: Math.min(tip.x, w - 220), top: tip.y + 22 }}>{tip.t}</div>}
    </div>
  )
}

/* =============================================================== lineage */
export interface LineageChain {
  scope: string; origin_actor: string; origin_event: string; origin_ts: string | null; origin_channel: string
  reusers: { actor: string; event: string; ts: string | null; exposed_via: string | null; channel: string | null }[]
}

export function Lineage({ chains }: { chains: LineageChain[] }) {
  const [ref, { w }] = useSize<HTMLDivElement>()
  const open = useStore((s) => s.openDrawer)
  return (
    <div ref={ref} className="stack" style={{ gap: 14 }}>
      {chains.map((c) => {
        const times = [c.origin_ts, ...c.reusers.map((r) => r.ts)].filter(Boolean).map((t) => +iso(t!))
        const lo = Math.min(...times), hi = Math.max(...times, lo + 60000)
        const x = scaleLinear().domain([lo, hi]).range([18, w - 18])
        const h = 30 + c.reusers.length * 20
        const ox = x(+iso(c.origin_ts!)), oy = 18
        return (
          <div key={c.scope}>
            <div className="row" style={{ gap: 8, marginBottom: 2 }}>
              <span style={{ fontWeight: 600 }}>{c.origin_actor}</span>
              <span className="muted">first posted {c.origin_channel && c.origin_channel !== 'unknown' ? `in ${c.origin_channel}` : '(place not recorded)'}</span>
              <span className="mono muted" style={{ marginLeft: 'auto' }}>{fmtTime(c.origin_ts, true)}</span>
            </div>
            <svg className="chart" width={w} height={h}>
              {c.reusers.map((r, i) => {
                const rx = x(+iso(r.ts!)), ry = oy + 18 + i * 20
                return (
                  <g key={r.event} style={{ cursor: 'pointer' }} onClick={() => open({ kind: 'event', id: r.event })}>
                    <path d={`M${ox},${oy} C${ox},${ry} ${ox},${ry} ${rx},${ry}`} fill="none"
                      stroke={r.exposed_via ? 'var(--st-observed)' : 'var(--st-unknown)'} strokeWidth={1.75}
                      strokeDasharray={r.exposed_via ? undefined : '4 4'} />
                    <circle cx={rx} cy={ry} r={5} fill={r.exposed_via ? 'var(--st-observed)' : 'var(--surface)'}
                      stroke={r.exposed_via ? 'var(--surface)' : 'var(--st-unknown)'} strokeWidth={2} />
                    <text x={rx + (rx > w - 160 ? -9 : 9)} y={ry + 3.5} textAnchor={rx > w - 160 ? 'end' : 'start'}
                      style={{ fontFamily: 'var(--font-ui)', fontSize: 11.5, fill: 'var(--ink-2)' }}>
                      {r.actor} · {r.exposed_via ? 'we saw where they got it' : 'came later, source not seen'}
                    </text>
                  </g>
                )
              })}
              <circle cx={ox} cy={oy} r={6.5} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2}
                style={{ cursor: 'pointer' }} onClick={() => open({ kind: 'event', id: c.origin_event })} />
            </svg>
          </div>
        )
      })}
      <div className="row mono muted" style={{ gap: 14 }}>
        <span className="row" style={{ gap: 5 }}><svg width="22" height="6"><line x1="0" x2="22" y1="3" y2="3" stroke="var(--st-observed)" strokeWidth="2" /></svg>observed exposure path</span>
        <span className="row" style={{ gap: 5 }}><svg width="22" height="6"><line x1="0" x2="22" y1="3" y2="3" stroke="var(--st-unknown)" strokeWidth="2" strokeDasharray="4 4" /></svg>later, source not seen</span>
      </div>
    </div>
  )
}

/* =============================================================== sparkline */
export function Sparkline({ values, width = 120, height = 26, color = 'var(--accent)', fluid = false, area = false }: { values: number[]; width?: number; height?: number; color?: string; fluid?: boolean; area?: boolean }) {
  const box = fluid ? { width: '100%', height, viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: 'none' } : { width, height }
  if (values.length < 2) return <svg {...box} />
  const x = scaleLinear().domain([0, values.length - 1]).range([1, width - 1])
  const y = scaleLinear().domain([0, Math.max(...values, 1)]).range([height - 2, 2])
  const p = line<number>().x((_, i) => x(i)).y((v) => y(v)).curve(curveMonotoneX)
  const d = p(values) || ''
  return (
    <svg {...box} className="spark">
      {area && <path d={`${d}L${x(values.length - 1)},${height}L${x(0)},${height}Z`} fill={color} opacity={0.1} />}
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

/* =============================================================== hooks */
export function useView<T>(name: string, params: Record<string, string | number | undefined> = {}, every = 1): T | null {
  const tick = useStore((s) => s.tick)
  const [data, set] = useState<T | null>(null)
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)])).toString()
  const bucket = Math.floor(tick / every)
  useEffect(() => {
    let live = true
    fetch(`/api/views/${name}${qs ? '?' + qs : ''}`).then((r) => (r.ok ? r.json() : null)).then((d) => live && d && set(d)).catch(() => {})
    return () => { live = false }
  }, [name, qs, bucket])
  return data
}
