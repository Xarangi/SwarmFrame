import React, { useEffect, useMemo, useState } from 'react'
import { area, curveMonotoneX, stack } from 'd3-shape'
import { scaleLinear } from 'd3-scale'
import { useStore } from '../store'
import type { PanelSpec, ViewData } from '../types'
import { Empty, fmtNum, fmtTick } from '../components/ui'
import { useSize } from './charts'

const PALETTE = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)', 'var(--c5)', 'var(--c6)', 'var(--c7)', 'var(--c8)']
const color = (i: number) => PALETTE[i % PALETTE.length]

/** Fetch a custom panel's data, refreshing as the stream advances (every other snapshot). */
export function usePanelData(page: string, panel: PanelSpec, version: number): ViewData | null {
  const tick = useStore((s) => s.tick)
  const [d, setD] = useState<ViewData | null>(null)
  const slow = Math.floor(tick / 2)
  useEffect(() => {
    if (panel.kind !== 'view' || !panel.view || panel.view.primitive === 'note') return
    let live = true
    fetch(`/api/dashboard/data/${page}/${panel.id}`).then((r) => r.json()).then((x) => { if (live) setD(x) }).catch(() => {})
    return () => { live = false }
  }, [page, panel.id, version, slow])
  return d
}

export function ViewBody({ page, panel, version }: { page: string; panel: PanelSpec; version: number }) {
  const data = usePanelData(page, panel, version)
  const v = panel.view!
  if (v.primitive === 'note') return <Note text={String(v.options?.text ?? '')} />
  if (!data) return <div className="skeleton" style={{ height: v.primitive === 'stat' ? 54 : 150 }} />
  return <ViewChart primitive={v.primitive} data={data} options={{ ...v.options, link: (v as any).link }} />
}

/** Draw a view's result. Also used by the view builder's preview. */
export function ViewChart({ primitive, data, options = {} }: { primitive: string; data: ViewData; options?: Record<string, any> }) {
  if (data.meta?.error) return <Empty title="This view could not run.">{data.meta.error}</Empty>
  if (!data.rows.length) return <Empty title="Nothing yet at this point in the stream.">The view fills in as the replay advances.</Empty>
  const link = options?.link !== 'none'
  switch (primitive) {
    case 'stat': return <Stat data={data} unit={options?.unit} />
    case 'timeseries': return <TimeSeries data={data} />
    case 'bar': return <Bars data={data} link={link} />
    case 'heatmap': return <Heatmap data={data} />
    case 'feed': return <Feed data={data} />
    case 'graph': return <Graph data={data} link={link} />
    case 'bipartite': return <Bipartite data={data} link={link} />
    case 'swimlane': return <Swimlane data={data} link={link} />
    default: return <Table data={data} link={link} />
  }
}

/** The entity behind a row's label, when the query grouped by actor or object: a click opens its evidence. */
function rowEntity(data: ViewData, i: number, col = 0): string | null {
  const ids = (data.meta as any)?.ids as (string | null)[][] | undefined
  return ids?.[i]?.[col] ?? null
}
const openEntity = (id: string | null) => { if (id) useStore.getState().openDrawer({ kind: 'entity', id }) }

function Note({ text }: { text: string }) {
  return (
    <div style={{ fontSize: 14, lineHeight: 1.55, color: 'var(--ink-2)', maxWidth: 820 }}>
      {text.split(/\n{2,}/).map((p, i) => <p key={i} style={{ margin: i ? '8px 0 0' : 0 }}>{p}</p>)}
    </div>
  )
}

function Stat({ data, unit }: { data: ViewData; unit?: string }) {
  if (data.columns.length === 1) {
    return (
      <div style={{ padding: '6px 0 2px' }}>
        <div className="display" style={{ fontSize: 44, lineHeight: 1 }}>{fmtNum(Number(data.rows[0][0]))}</div>
        {unit && <div className="label" style={{ marginTop: 6 }}>{unit}</div>}
      </div>
    )
  }
  return (
    <div className="row" style={{ flexWrap: 'wrap', gap: 16 }}>
      {data.rows.slice(0, 6).map((r, i) => (
        <div key={i}>
          <div className="display" style={{ fontSize: 30, lineHeight: 1 }}>{fmtNum(Number(r[r.length - 1]))}</div>
          <div className="label" style={{ marginTop: 4 }}>{String(r[0])}</div>
        </div>
      ))}
    </div>
  )
}

function Bars({ data, link = true }: { data: ViewData; link?: boolean }) {
  const max = Math.max(1, ...data.rows.map((r) => Number(r[r.length - 1])))
  return (
    <div className="stack" style={{ gap: 5 }}>
      {data.rows.slice(0, 15).map((r, i) => {
        const v = Number(r[r.length - 1])
        const lab = r.slice(0, -1).join(' · ')
        const ent = link ? rowEntity(data, i) : null
        return (
          <div key={i} className={`bars-row ${ent ? 'link' : ''}`} onClick={ent ? () => openEntity(ent) : undefined} title={ent ? 'Open the records' : undefined}>
            <span title={lab} style={{ fontSize: 13, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{lab}</span>
            <div className="bar-track" style={{ height: 8 }}><div className="bar-fill" style={{ width: `${(v / max) * 100}%`, background: 'var(--data)' }} /></div>
            <span className="mono" style={{ textAlign: 'right' }}>{fmtNum(v)}</span>
          </div>
        )
      })}
    </div>
  )
}

function TimeSeries({ data }: { data: ViewData }) {
  const [ref, { w }] = useSize<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const two = data.columns.length === 3
  const { times, series, table } = useMemo(() => {
    const ti = (data.meta?.time_dims?.[0] ?? 0) as number
    const si = two ? 1 - ti : -1
    const times = [...new Set(data.rows.map((r) => String(r[ti])))].sort()
    const tot: Record<string, number> = {}
    data.rows.forEach((r) => { const k = si >= 0 ? String(r[si]) : 'value'; tot[k] = (tot[k] ?? 0) + Number(r[r.length - 1]) })
    const series = Object.keys(tot).sort((a, b) => tot[b] - tot[a]).slice(0, 8)
    const idx = new Map(times.map((t, i) => [t, i]))
    const table = times.map((t) => Object.fromEntries([['t', t], ...series.map((s) => [s, 0])])) as Record<string, any>[]
    data.rows.forEach((r) => {
      const k = si >= 0 ? String(r[si]) : 'value'
      if (series.includes(k)) table[idx.get(String(r[ti]))!][k] += Number(r[r.length - 1])
    })
    return { times, series, table }
  }, [data, two])
  if (times.length < 2) return <div ref={ref}><Empty title="Collecting: a trend needs at least two time buckets." /></div>
  const h = 180, padL = 34, padB = 20
  const stacked = stack<Record<string, any>>().keys(series)(table)
  const ymax = Math.max(1, ...stacked.flatMap((s) => s.map((p) => p[1])))
  const x = scaleLinear().domain([0, Math.max(1, times.length - 1)]).range([padL, Math.max(padL + 10, w - 8)])
  const y = scaleLinear().domain([0, ymax]).nice().range([h - padB, 8])
  const mk = area<any>().x((_, i) => x(i)).y0((p) => y(p[0])).y1((p) => y(p[1])).curve(curveMonotoneX)
  const span = times.length > 1 ? +new Date(times[times.length - 1].replace(' ', 'T') + 'Z') - +new Date(times[0].replace(' ', 'T') + 'Z') : 0
  const fmtT = (t: string) => (/^\d{4}-\d\d-\d\d/.test(t) ? fmtTick(new Date(t.replace(' ', 'T') + (t.length > 10 ? 'Z' : 'T00:00Z')), span || 86400e3) : t)
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <svg width={w} height={h} onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => setHover(Math.round(x.invert(e.clientX - e.currentTarget.getBoundingClientRect().left)))}>
        {y.ticks(4).map((t) => (
          <g key={t}><line x1={padL} x2={w - 8} y1={y(t)} y2={y(t)} stroke="var(--line-2)" />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" className="mono" fontSize={10} fill="var(--ink-3)">{fmtNum(t)}</text></g>
        ))}
        {stacked.map((s, i) => <path key={s.key} d={mk(s as any) ?? ''} fill={color(i)} fillOpacity={0.82} />)}
        {[0, Math.floor((times.length - 1) / 2), times.length - 1].filter((v, i, a) => a.indexOf(v) === i && v >= 0).map((i) => (
          <text key={i} x={x(i)} y={h - 5} textAnchor={i === 0 ? 'start' : i === times.length - 1 ? 'end' : 'middle'} className="mono" fontSize={10} fill="var(--ink-3)">{fmtT(times[i] ?? '')}</text>
        ))}
        {hover !== null && hover >= 0 && hover < times.length && <line x1={x(hover)} x2={x(hover)} y1={8} y2={h - padB} stroke="var(--ink-3)" strokeDasharray="2 3" />}
      </svg>
      {hover !== null && hover >= 0 && hover < times.length && (
        <div className="card" style={{ position: 'absolute', top: 0, left: Math.min(Math.max(0, x(hover) + 10), Math.max(0, w - 200)), pointerEvents: 'none', padding: '6px 9px', minWidth: 150, boxShadow: 'var(--shadow-1)' }}>
          <div className="mono muted">{fmtT(times[hover])}</div>
          {series.map((s, i) => table[hover][s] ? (
            <div key={s} className="row mono" style={{ gap: 6, justifyContent: 'space-between' }}>
              <span className="row" style={{ gap: 5 }}><span style={{ width: 8, height: 8, borderRadius: 2, background: color(i) }} />{s}</span><span>{fmtNum(table[hover][s])}</span></div>
          ) : null)}
        </div>
      )}
      {two && (
        <div className="row" style={{ flexWrap: 'wrap', gap: 10, marginTop: 4 }}>
          {series.map((s, i) => <span key={s} className="row mono" style={{ gap: 5 }}><span style={{ width: 9, height: 9, borderRadius: 2, background: color(i) }} />{s}</span>)}
        </div>
      )}
    </div>
  )
}

function Heatmap({ data }: { data: ViewData }) {
  const [ref, { w }] = useSize<HTMLDivElement>()
  const { rows, cols, cell, max } = useMemo(() => {
    const timeDims: number[] = data.meta?.time_dims ?? []
    const rowsTot: Record<string, number> = {}, colsTot: Record<string, number> = {}
    const cell: Record<string, number> = {}
    data.rows.forEach((r) => {
      const a = String(r[0]), b = String(r[1]), v = Number(r[2])
      rowsTot[a] = (rowsTot[a] ?? 0) + v; colsTot[b] = (colsTot[b] ?? 0) + v; cell[`${a}\u0000${b}`] = v
    })
    const rows = Object.keys(rowsTot).sort((a, b) => rowsTot[b] - rowsTot[a]).slice(0, 20)
    const cols = timeDims.includes(1) ? Object.keys(colsTot).sort() : Object.keys(colsTot).sort((a, b) => colsTot[b] - colsTot[a]).slice(0, 24)
    return { rows, cols, cell, max: Math.max(1, ...Object.values(cell)) }
  }, [data])
  const labW = Math.min(230, Math.max(90, w * 0.32))
  const timeCols = (data.meta?.time_dims ?? []).includes(1)
  const cw = Math.max(4, Math.min(64, (w - labW - 8) / Math.max(1, cols.length)))
  const ch = 18
  const head = timeCols ? 0 : Math.min(84, 14 + 6 * Math.max(...cols.map((c) => Math.min(16, c.length))))
  return (
    <div ref={ref} style={{ overflowX: 'auto' }}>
      <svg width={w} height={head + rows.length * ch + (timeCols ? 26 : 6)}>
        {!timeCols && cols.map((c, j) => (
          <text key={c} transform={`translate(${labW + j * cw + cw / 2 + 3}, ${head - 6}) rotate(-38)`} className="mono" fontSize={10} fill="var(--ink-3)">
            {c.length > 16 ? c.slice(0, 15) + '…' : c}<title>{c}</title></text>
        ))}
        {rows.map((r, i) => (
          <g key={r} transform={`translate(0, ${head + i * ch})`}>
            <text x={labW - 8} y={ch * 0.68} textAnchor="end" fontSize={12} fill="var(--ink-2)">{r.length > 34 ? r.slice(0, 33) + '…' : r}<title>{r}</title></text>
            {cols.map((c, j) => {
              const v = cell[`${r}\u0000${c}`] ?? 0
              return <rect key={c} x={labW + j * cw} y={2} width={Math.max(1, cw - 1.5)} height={ch - 3} rx={2}
                fill={v ? 'var(--data)' : 'color-mix(in srgb, var(--ink) 6%, transparent)'} fillOpacity={v ? 0.15 + 0.85 * Math.sqrt(v / max) : 1}><title>{`${r} · ${c}: ${v}`}</title></rect>
            })}
          </g>
        ))}
        {timeCols && [0, cols.length - 1].filter((v, i, a) => a.indexOf(v) === i).map((j) => (
          <text key={j} x={labW + j * cw + (j ? cw : 0)} y={head + rows.length * ch + 16} textAnchor={j ? 'end' : 'start'} className="mono" fontSize={10} fill="var(--ink-3)">{cols[j]?.slice(0, 10)}</text>))}
      </svg>
    </div>
  )
}

function Table({ data, link = true }: { data: ViewData; link?: boolean }) {
  return (
    <div style={{ maxHeight: 360, overflow: 'auto' }}>
      <table className="t" style={{ fontSize: 13 }}>
        <thead><tr>{data.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {data.rows.slice(0, 60).map((r, i) => (
            <tr key={i}>{r.map((v, j) => {
              const ent = link ? rowEntity(data, i, j) : null
              return <td key={j} className={typeof v === 'number' ? 'num' : ''}>{ent ? <button className="claim-ref" onClick={() => openEntity(ent)}>{String(v)}</button> : typeof v === 'number' ? fmtNum(v) : String(v)}</td>
            })}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** The latest matching records, newest first; each opens in the evidence drawer. */
function Feed({ data }: { data: ViewData }) {
  const eids = ((data.meta as any)?.event_ids ?? []) as string[]
  return (
    <div className="feed">
      {data.rows.map((r, i) => (
        <div key={i} className="feed-row" onClick={() => eids[i] && useStore.getState().openDrawer({ kind: 'event', id: eids[i] })} title="Open the record">
          <span className="mono muted">{String(r[0]).slice(5, 16)}</span>
          <span className="what"><b>{String(r[1] || 'someone')}</b> {String(r[2])}{r[3] ? <> on <b>{String(r[3])}</b></> : null}</span>
        </div>
      ))}
    </div>
  )
}

/** Who works with whom: nodes of the first dimension, linked when they share values of the second. */
function Graph({ data, link = true }: { data: ViewData; link?: boolean }) {
  const [ref, { w }] = useSize<HTMLDivElement>()
  const h = 300
  const g = useMemo(() => {
    const tot: Record<string, number> = {}, idOf: Record<string, string | null> = {}
    const by: Record<string, Set<string>> = {}
    data.rows.forEach((r, i) => {
      const a = String(r[0]), b = String(r[1]), v = Number(r[2])
      tot[a] = (tot[a] ?? 0) + v
      idOf[a] = rowEntity(data, i, 0)
      ;(by[b] ??= new Set()).add(a)
    })
    const nodes = Object.keys(tot).sort((x, y) => tot[y] - tot[x]).slice(0, 36)
    const keep = new Set(nodes)
    const ew: Record<string, number> = {}
    Object.values(by).forEach((set) => {
      const xs = [...set].filter((x) => keep.has(x))
      for (let i = 0; i < xs.length; i++) for (let j = i + 1; j < xs.length; j++) { const k = xs[i] < xs[j] ? `${xs[i]}\u0000${xs[j]}` : `${xs[j]}\u0000${xs[i]}`; ew[k] = (ew[k] ?? 0) + 1 }
    })
    const edges = Object.entries(ew).sort((a, b) => b[1] - a[1]).slice(0, 120).map(([k, v]) => { const [a, b] = k.split('\u0000'); return { a, b, v } })
    // a small deterministic force layout: pull along edges, push apart, keep inside
    const pos: Record<string, { x: number; y: number }> = {}
    nodes.forEach((n, i) => { const t = (i / Math.max(1, nodes.length)) * Math.PI * 2; pos[n] = { x: Math.cos(t) * 0.3, y: Math.sin(t) * 0.3 } })
    for (let it = 0; it < 220; it++) {
      const f: Record<string, { x: number; y: number }> = Object.fromEntries(nodes.map((n) => [n, { x: -pos[n].x * 0.05, y: -pos[n].y * 0.05 }]))
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const p = pos[nodes[i]], q = pos[nodes[j]]; const dx = p.x - q.x, dy = p.y - q.y; const d2 = Math.max(0.002, dx * dx + dy * dy)
        const k = 0.0016 / d2; f[nodes[i]].x += dx * k; f[nodes[i]].y += dy * k; f[nodes[j]].x -= dx * k; f[nodes[j]].y -= dy * k
      }
      const emax = Math.max(1, ...edges.map((e) => e.v))
      edges.forEach((e) => { const p = pos[e.a], q = pos[e.b]; const dx = q.x - p.x, dy = q.y - p.y; const k = 0.04 * (e.v / emax); f[e.a].x += dx * k; f[e.a].y += dy * k; f[e.b].x -= dx * k; f[e.b].y -= dy * k })
      nodes.forEach((n) => { pos[n].x = Math.max(-0.44, Math.min(0.44, pos[n].x + f[n].x)); pos[n].y = Math.max(-0.42, Math.min(0.42, pos[n].y + f[n].y)) })
    }
    return { nodes, edges, tot, pos, idOf, max: Math.max(1, ...Object.values(tot)), emax: Math.max(1, ...edges.map((e) => e.v)) }
  }, [data])
  const X = (x: number) => w / 2 + x * (w - 40), Y = (y: number) => h / 2 + y * (h - 30)
  return (
    <div ref={ref}>
      <svg width={w} height={h}>
        {g.edges.map((e, i) => <line key={i} x1={X(g.pos[e.a].x)} y1={Y(g.pos[e.a].y)} x2={X(g.pos[e.b].x)} y2={Y(g.pos[e.b].y)} stroke="var(--ink-3)" strokeOpacity={0.12 + 0.5 * (e.v / g.emax)} strokeWidth={0.6 + 2 * (e.v / g.emax)} />)}
        {g.nodes.map((n, i) => {
          const r = 3.5 + 9 * Math.sqrt(g.tot[n] / g.max)
          return (
            <g key={n} className="graph-node" transform={`translate(${X(g.pos[n].x)}, ${Y(g.pos[n].y)})`} onClick={link ? () => openEntity(g.idOf[n]) : undefined}>
              <circle r={r} fill={i < 8 ? 'var(--data)' : 'var(--ink-4)'} fillOpacity={0.85} stroke="var(--surface)" strokeWidth={1.2}><title>{`${n}: ${fmtNum(g.tot[n])}`}</title></circle>
              {i < 12 && <text x={X(g.pos[n].x) > w - 110 ? -(r + 3) : r + 3} y={3.5} textAnchor={X(g.pos[n].x) > w - 110 ? 'end' : 'start'} fontSize={10.5} fill="var(--ink-2)">{n.length > 18 ? n.slice(0, 17) + '…' : n}</text>}
            </g>
          )
        })}
      </svg>
      <div className="muted" style={{ fontSize: 11.5 }}>Linked when they share a {data.columns[1]}; thicker lines share more. Click a node to open its records.</div>
    </div>
  )
}

/** Two columns joined by lines weighted by count. */
function Bipartite({ data, link = true }: { data: ViewData; link?: boolean }) {
  const [ref, { w }] = useSize<HTMLDivElement>()
  const g = useMemo(() => {
    const ta: Record<string, number> = {}, tb: Record<string, number> = {}, ida: Record<string, string | null> = {}, idb: Record<string, string | null> = {}
    data.rows.forEach((r, i) => { const a = String(r[0]), b = String(r[1]), v = Number(r[2]); ta[a] = (ta[a] ?? 0) + v; tb[b] = (tb[b] ?? 0) + v; ida[a] = rowEntity(data, i, 0); idb[b] = rowEntity(data, i, 1) })
    const A = Object.keys(ta).sort((x, y) => ta[y] - ta[x]).slice(0, 14), B = Object.keys(tb).sort((x, y) => tb[y] - tb[x]).slice(0, 14)
    const links = data.rows.filter((r) => A.includes(String(r[0])) && B.includes(String(r[1]))).map((r) => ({ a: String(r[0]), b: String(r[1]), v: Number(r[2]) }))
    return { A, B, links, ida, idb, max: Math.max(1, ...links.map((l) => l.v)) }
  }, [data])
  const rowH = 20, h = Math.max(g.A.length, g.B.length) * rowH + 10, labW = Math.min(170, w * 0.3)
  const ya = (a: string) => 10 + g.A.indexOf(a) * rowH, yb = (b: string) => 10 + g.B.indexOf(b) * rowH
  return (
    <div ref={ref}>
      <svg width={w} height={h}>
        {g.links.map((l, i) => { const x1 = labW + 6, x2 = w - labW - 6, y1 = ya(l.a), y2 = yb(l.b)
          return <path key={i} d={`M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`} fill="none" stroke="var(--data)" strokeOpacity={0.15 + 0.6 * (l.v / g.max)} strokeWidth={0.8 + 3 * (l.v / g.max)}><title>{`${l.a} → ${l.b}: ${l.v}`}</title></path> })}
        {g.A.map((a) => <text key={a} className="lane-label" x={labW} y={ya(a) + 4} textAnchor="end" onClick={link ? () => openEntity(g.ida[a]) : undefined}>{a.length > 24 ? a.slice(0, 23) + '…' : a}</text>)}
        {g.B.map((b) => <text key={b} className="lane-label" x={w - labW} y={yb(b) + 4} onClick={link ? () => openEntity(g.idb[b]) : undefined}>{b.length > 24 ? b.slice(0, 23) + '…' : b}</text>)}
      </svg>
    </div>
  )
}

/** One lane per value of the first dimension; marks over time sized by count. */
function Swimlane({ data, link = true }: { data: ViewData; link?: boolean }) {
  const [ref, { w }] = useSize<HTMLDivElement>()
  const g = useMemo(() => {
    const ti = ((data.meta as any)?.time_dims?.[0] ?? 1) as number, li = 1 - ti
    const tot: Record<string, number> = {}, ids: Record<string, string | null> = {}
    data.rows.forEach((r, i) => { const k = String(r[li]); tot[k] = (tot[k] ?? 0) + Number(r[2]); ids[k] = rowEntity(data, i, li) })
    const lanes = Object.keys(tot).sort((a, b) => tot[b] - tot[a]).slice(0, 16)
    const times = [...new Set(data.rows.map((r) => String(r[ti])))].sort()
    const pts = data.rows.filter((r) => lanes.includes(String(r[li]))).map((r) => ({ lane: String(r[li]), t: String(r[ti]), v: Number(r[2]) }))
    return { lanes, times, pts, ids, max: Math.max(1, ...pts.map((p) => p.v)) }
  }, [data])
  const labW = Math.min(170, w * 0.3), rowH = 20, h = g.lanes.length * rowH + 24
  const x = (t: string) => labW + 8 + (g.times.indexOf(t) / Math.max(1, g.times.length - 1)) * (w - labW - 20)
  return (
    <div ref={ref}>
      <svg width={w} height={h}>
        {g.lanes.map((l, i) => <g key={l}><line x1={labW + 4} x2={w - 6} y1={i * rowH + 12} y2={i * rowH + 12} stroke="var(--line-2)" />
          <text className="lane-label" x={labW} y={i * rowH + 16} textAnchor="end" onClick={link ? () => openEntity(g.ids[l]) : undefined}>{l.length > 24 ? l.slice(0, 23) + '…' : l}</text></g>)}
        {g.pts.map((p, i) => <circle key={i} cx={x(p.t)} cy={g.lanes.indexOf(p.lane) * rowH + 12} r={1.5 + 6 * Math.sqrt(p.v / g.max)} fill="var(--data)" fillOpacity={0.75}><title>{`${p.lane} · ${p.t}: ${p.v}`}</title></circle>)}
        {g.times.length > 1 && [0, g.times.length - 1].map((j) => <text key={j} x={x(g.times[j])} y={h - 4} textAnchor={j ? 'end' : 'start'} className="mono" fontSize={10} fill="var(--ink-3)">{g.times[j].slice(0, 16)}</text>)}
      </svg>
    </div>
  )
}
