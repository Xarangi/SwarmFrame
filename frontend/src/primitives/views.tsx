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
  return <ViewChart primitive={v.primitive} data={data} options={v.options} />
}

/** Draw a view's result. Also used by the view builder's preview. */
export function ViewChart({ primitive, data, options = {} }: { primitive: string; data: ViewData; options?: Record<string, any> }) {
  if (data.meta?.error) return <Empty title="This view could not run.">{data.meta.error}</Empty>
  if (!data.rows.length) return <Empty title="Nothing yet at this point in the stream.">The view fills in as the replay advances.</Empty>
  switch (primitive) {
    case 'stat': return <Stat data={data} unit={options?.unit} />
    case 'timeseries': return <TimeSeries data={data} />
    case 'bar': return <Bars data={data} />
    case 'heatmap': return <Heatmap data={data} />
    default: return <Table data={data} />
  }
}

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

function Bars({ data }: { data: ViewData }) {
  const max = Math.max(1, ...data.rows.map((r) => Number(r[r.length - 1])))
  return (
    <div className="stack" style={{ gap: 7 }}>
      {data.rows.slice(0, 15).map((r, i) => {
        const v = Number(r[r.length - 1])
        const lab = r.slice(0, -1).join(' · ')
        return (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: 'minmax(90px, 38%) 1fr 52px', gap: 10, alignItems: 'center' }}>
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

function Table({ data }: { data: ViewData }) {
  return (
    <div style={{ maxHeight: 360, overflow: 'auto' }}>
      <table className="tbl" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead><tr>{data.columns.map((c) => <th key={c} className="label" style={{ textAlign: 'left', padding: '4px 8px 6px 0', borderBottom: '1px solid var(--line)' }}>{c}</th>)}</tr></thead>
        <tbody>
          {data.rows.slice(0, 60).map((r, i) => (
            <tr key={i}>{r.map((v, j) => <td key={j} className={typeof v === 'number' ? 'mono' : ''} style={{ padding: '5px 8px 5px 0', borderBottom: '1px solid var(--line-2)', verticalAlign: 'top' }}>{typeof v === 'number' ? fmtNum(v) : String(v)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
