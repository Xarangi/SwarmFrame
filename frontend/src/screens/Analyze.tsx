import React, { useEffect, useMemo, useRef, useState } from 'react'
import { get, post } from '../api'
import { useStore } from '../store'
import { Icon } from '../components/ui'
import { prettyModel, type LlmOptions } from '../components/ReadingSetup'
import { markComposed } from './Compose'

/** Post-analysis: a dump in, a report out. A side mode beside live monitoring: point at a folder or drop files,
 *  check what SwarmFrame found in them, and read the whole record at once. The report cites record ids; open the
 *  analysis in the dashboard to explore it with every page and the evidence drawer. */

type Role = 'ts' | 'actor' | 'action' | 'object' | 'group' | 'family' | 'text' | 'id'
const ROLE_LABEL: Record<Role, string> = { ts: 'time', actor: 'who', action: 'what they did', object: 'what they acted on', group: 'group', family: 'kind', text: 'their text', id: 'record id' }
interface DFile { file: string; size?: number; rows: number; rows_capped?: boolean; fields?: string[]; mapping?: Record<Role, string | null>; usable?: boolean; error?: string }
interface Detected { path: string; known: string | null; known_title: string | null; files: DFile[]; rows: number; usable: boolean }
interface Job { id: string; path: string; source: string; status: string; progress: number; message: string; error: string; seconds: number
  has_report: boolean; words: number; written_words: number; writer?: { model: string; cost_usd: number; tool_calls: number } | null
  markdown?: string; written?: string; options?: Record<string, any> }

export function Analyze() {
  const [path, setPath] = useState(() => localStorage.getItem('ss.dumpPath') || '')
  const [det, setDet] = useState<Detected | null>(null)
  const [maps, setMaps] = useState<Record<string, Record<Role, string | null>>>({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [over, setOver] = useState(false)
  const [writer, setWriter] = useState<'rules' | 'claude'>('rules')
  const [model, setModel] = useState('claude-sonnet-5-5')
  const [effort, setEffort] = useState('low')
  const [opts, setOpts] = useState<LlmOptions | null>(null)
  const [title, setTitle] = useState('')
  const [fix, setFix] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [recent, setRecent] = useState<Job[]>([])
  const pick = useRef<HTMLInputElement>(null)
  useEffect(() => { get<LlmOptions>('/api/llm/options').then(setOpts).catch(() => {}); get<Job[]>('/api/analysis').then(setRecent).catch(() => {}) }, [])
  const claudeOk = !!opts?.providers.find((p) => p.id !== 'none' && p.available)

  const got = (d: Detected) => { setDet(d); setMaps(Object.fromEntries(d.files.filter((f) => f.mapping).map((f) => [f.file, { ...f.mapping! }]))); setPath(d.path) }
  const look = async (p = path) => {
    setErr(''); setDet(null); setBusy(true)
    try { localStorage.setItem('ss.dumpPath', p); got(await post<Detected>('/api/analysis/detect', { path: p })) }
    catch (e: any) { setErr(String(e.message || e).replace(/^\d+ /, '').replace(/^\{"detail":"(.*)"\}$/, '$1')) } finally { setBusy(false) }
  }
  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    setErr(''); setBusy(true)
    const fd = new FormData()
    Array.from(files).forEach((f) => fd.append('files', f))
    try { const r = await fetch('/api/analysis/upload', { method: 'POST', body: fd }); const d = await r.json(); if (!r.ok) throw new Error(d.detail); got(d) }
    catch (e: any) { setErr(String(e.message || e)) } finally { setBusy(false) }
  }
  const run = async () => {
    if (!det) return
    setErr('')
    const mapping = det.known ? undefined : Object.fromEntries(Object.entries(maps).filter(([, m]) => m.ts))
    try {
      const j = await post<Job>('/api/analysis/start', { path: det.path, options: { mapping, title, write: writer, model, effort } })
      setJob(j)
    } catch (e: any) { setErr(String(e.message || e).replace(/^\d+ /, '')) }
  }
  useEffect(() => {
    if (!job || job.status === 'done' || job.status === 'error') return
    const t = setInterval(() => get<Job>(`/api/analysis/${job.id}`).then(setJob).catch(() => {}), 800)
    return () => clearInterval(t)
  }, [job?.id, job?.status])

  if (job && job.status === 'done' && job.has_report) return <ReportView job={job} onBack={() => { setJob(null); get<Job[]>('/api/analysis').then(setRecent).catch(() => {}) }} />

  return (
    <div className="analyze fade-in">
      <div className="label" style={{ marginBottom: 6 }}>Post-analysis</div>
      <h1 className="compose-title" style={{ fontSize: 'calc(38px * var(--headline))' }}>Analyze a dump</h1>
      <p className="compose-lede">Point SwarmFrame at logs you already have. It reads the whole record at once with the same watchers and analysts as live monitoring, then writes a report where every claim names the records behind it.</p>

      {job ? (
        <section className="surface" style={{ marginTop: 22, padding: 18 }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <b>{job.status === 'error' ? 'The analysis stopped' : job.status === 'writing' ? 'Claude is writing the report' : 'Reading the record'}</b>
            <span className="mono muted">{job.seconds.toFixed(0)} s</span>
          </div>
          <div className="progress" style={{ margin: '12px 0 8px' }}><i style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
          <div className="mono muted" style={{ fontSize: 11.5 }}>{job.status === 'error' ? job.error : job.message}</div>
          <div className="row" style={{ marginTop: 12 }}>
            {job.status === 'error' ? <button className="btn" onClick={() => setJob(null)}>Back</button>
              : <button className="btn ghost" onClick={() => post(`/api/analysis/${job.id}/stop`).then(() => setJob(null))}>Stop</button>}
          </div>
        </section>
      ) : (
        <>
          <section className={`analyze-drop ${over ? 'over' : ''}`} style={{ marginTop: 22 }}
            onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files) }}>
            <form className="row" style={{ gap: 8 }} onSubmit={(e) => { e.preventDefault(); if (path.trim()) look() }}>
              <input className="input" value={path} onChange={(e) => setPath(e.target.value)} placeholder="A folder or file on this computer, e.g. C:\logs\swarm-run or ~/exports/events.jsonl.gz" aria-label="Path to the dump" />
              <button className="btn primary" type="submit" disabled={busy || !path.trim()}>{busy ? 'Looking…' : 'Look'}</button>
            </form>
            <div className="row" style={{ gap: 8, fontSize: 13 }}>
              <span className="muted">or drop files here, or</span>
              <button className="link" onClick={() => pick.current?.click()}><Icon name="upload" size={14} />choose files</button>
              <input ref={pick} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
              <span className="muted">· no dump at hand?</span>
              <button className="link" onClick={async () => { setBusy(true); try { got(await post<Detected>('/api/analysis/sample')) } finally { setBusy(false) } }}>use a sample</button>
              <span className="muted" style={{ marginLeft: 'auto', fontSize: 12 }}>JSON, JSON lines, CSV; gzipped or zipped</span>
            </div>
          </section>
          {err && <div className="theme-error" style={{ marginTop: 10 }}>{err}</div>}

          {det && (
            <section className="surface" style={{ marginTop: 16, padding: 18 }}>
              <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
                <b>{det.known ? `${det.known_title}: read with its own reader` : `${det.files.filter((f) => maps[f.file]?.ts).length} of ${det.files.length} files can be read as events`}</b>
                <span className="mono muted">{det.rows.toLocaleString()} rows</span>
              </div>
              <div className="detected" style={{ marginTop: 10 }}>
                {det.files.map((f) => (
                  <div key={f.file} className="detected-file">
                    <span style={{ overflowWrap: 'anywhere' }}>{f.file}</span>
                    <span className="mono muted">{f.rows.toLocaleString()}{f.rows_capped ? '+' : ''} rows</span>
                    <span className="map-chips">
                      {f.error ? <span className="theme-error">{f.error}</span>
                        : det.known ? <span className="muted" style={{ fontSize: 12.5 }}>{(f.fields ?? []).slice(0, 8).join(', ')}{(f.fields ?? []).length > 8 ? '…' : ''}</span>
                        : maps[f.file]?.ts ? (Object.keys(ROLE_LABEL) as Role[]).filter((r) => maps[f.file]?.[r]).map((r) => <span key={r} className="map-chip">{ROLE_LABEL[r]}: <b>{maps[f.file][r]}</b></span>)
                        : <span className="muted" style={{ fontSize: 12.5 }}>no time field found, so not read as events</span>}
                    </span>
                  </div>
                ))}
              </div>
              {!det.known && <button className="link" style={{ marginTop: 10 }} onClick={() => setFix(!fix)}>{fix ? 'Done' : 'Fix the mapping'}</button>}
              {fix && !det.known && <MappingEditor files={det.files} maps={maps} setMaps={setMaps} />}

              <div style={{ marginTop: 18 }}>
                <div className="setup-h"><span className="label">Who writes the report</span></div>
                <div className="mode-pick two">
                  <button className={`mode-opt ${writer === 'rules' ? 'on' : ''}`} onClick={() => setWriter('rules')}>
                    <span className="mode-top"><span className="mode-dot" />Rules<span className="mode-cost">free · seconds</span></span>
                    <span className="mode-body">Counts, timing, groups and what the detectors raised, each with its records. Nothing leaves this machine.</span>
                  </button>
                  <button className={`mode-opt ${writer === 'claude' ? 'on' : ''}`} disabled={!claudeOk} onClick={() => setWriter('claude')}>
                    <span className="mode-top"><span className="mode-dot" />Claude<span className="mode-cost">model calls</span></span>
                    <span className="mode-body">{claudeOk ? 'Starts from the rules reading, checks and deepens it with the evidence tools, and writes it up with a confidence for each conclusion.' : 'Needs the Claude Code CLI on this machine.'}</span>
                  </button>
                </div>
                {writer === 'claude' && opts && (
                  <div className="row" style={{ gap: 10, marginTop: 10, flexWrap: 'wrap' }}>
                    <select className="input" style={{ maxWidth: 320 }} value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model">
                      {opts.models.map((m) => <option key={m.id} value={m.id}>{m.label} · {m.note}</option>)}
                    </select>
                    <div className="seg sm">{opts.efforts.map((x) => <button key={x} className={effort === x ? 'on' : ''} onClick={() => setEffort(x)}>{x} effort</button>)}</div>
                  </div>
                )}
              </div>
              <div className="run-actions" style={{ marginTop: 16 }}>
                <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="A title for the report (optional)" aria-label="Report title" />
                <button className="btn accent lg" disabled={!det.usable && !Object.values(maps).some((m) => m.ts)} onClick={run}>Analyze <Icon name="arrow" size={15} /></button>
              </div>
            </section>
          )}

          {recent.filter((j) => j.has_report).length > 0 && (
            <section style={{ marginTop: 26 }}>
              <div className="label" style={{ marginBottom: 8 }}>Earlier in this session</div>
              <div className="stack" style={{ gap: 6 }}>
                {recent.filter((j) => j.has_report).map((j) => (
                  <button key={j.id} className="card row" style={{ cursor: 'pointer', textAlign: 'left' }} onClick={() => get<Job>(`/api/analysis/${j.id}`).then(setJob)}>
                    <Icon name="file" size={16} /><span style={{ flex: 1, overflowWrap: 'anywhere' }}>{j.options?.title || j.path}</span>
                    <span className="mono muted">{j.words.toLocaleString()} words{j.written_words ? ` · Claude ${j.written_words.toLocaleString()}` : ''}</span>
                  </button>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function MappingEditor({ files, maps, setMaps }: { files: DFile[]; maps: Record<string, Record<Role, string | null>>; setMaps: (m: Record<string, Record<Role, string | null>>) => void }) {
  const roles: Role[] = ['ts', 'actor', 'action', 'object', 'group', 'text']
  return (
    <div className="stack" style={{ marginTop: 10, gap: 14 }}>
      {files.filter((f) => f.fields?.length).map((f) => (
        <div key={f.file}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>{f.file}</div>
          <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
            {roles.map((r) => (
              <label key={r} className="field" style={{ minWidth: 150 }}><span className="label">{ROLE_LABEL[r]}</span>
                <select className="input sm" value={maps[f.file]?.[r] ?? ''} onChange={(e) => setMaps({ ...maps, [f.file]: { ...(maps[f.file] ?? {} as any), [r]: e.target.value || null } })}>
                  <option value="">none</option>
                  {f.fields!.map((k) => <option key={k} value={k}>{k}</option>)}
                </select></label>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ the report */
function ReportView({ job, onBack }: { job: Job; onBack: () => void }) {
  const [tab, setTab] = useState<'claude' | 'rules'>(job.written ? 'claude' : 'rules')
  const md = tab === 'claude' ? job.written ?? '' : job.markdown ?? ''
  const openDash = async (then?: () => void) => {
    const r = await post<{ ok: boolean; session_id: string }>(`/api/analysis/${job.id}/open`)
    markComposed(r.session_id)
    useStore.getState().setRoute('brief')
    then && setTimeout(then, 600)
  }
  const openRecord = (id: string) => openDash(() => useStore.getState().openDrawer({ kind: 'event', id }))
  const download = () => {
    const blob = new Blob([md], { type: 'text/markdown' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${(job.options?.title || 'report').replace(/[^a-z0-9]+/gi, '-').toLowerCase()}${tab === 'claude' ? '-claude' : ''}.md`
    a.click()
    URL.revokeObjectURL(a.href)
  }
  return (
    <div className="report fade-in">
      <div className="report-head">
        <button className="btn ghost" onClick={onBack}><Icon name="arrow" size={14} />New analysis</button>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={download}><Icon name="download" size={14} />Download .md</button>
        <button className="btn" onClick={() => navigator.clipboard?.writeText(md)}>Copy</button>
        <button className="btn primary" onClick={() => openDash()}>Explore in the dashboard <Icon name="arrow" size={14} /></button>
      </div>
      {job.written && (
        <div className="seg report-tabs">
          <button className={tab === 'claude' ? 'on' : ''} onClick={() => setTab('claude')}>Written by {job.writer ? prettyModel(job.writer.model) : 'Claude'}</button>
          <button className={tab === 'rules' ? 'on' : ''} onClick={() => setTab('rules')}>The rules reading</button>
        </div>
      )}
      <div className="mono muted" style={{ fontSize: 11, marginBottom: 10 }}>
        {(tab === 'claude' ? job.written_words : job.words).toLocaleString()} words · read in {job.seconds.toFixed(0)} s
        {tab === 'claude' && job.writer ? ` · ${job.writer.tool_calls} evidence lookups · about $${job.writer.cost_usd.toFixed(2)}` : ''} · click a record id to open it
      </div>
      <article className="surface report-doc"><Markdown text={md} onRecord={openRecord} /></article>
    </div>
  )
}

/** A small Markdown renderer for reports: headings, paragraphs, lists, tables, quotes, bold, italics, code. */
export function Markdown({ text, onRecord }: { text: string; onRecord?: (id: string) => void }) {
  const blocks = useMemo(() => parse(text), [text])
  const inline = (s: string, k: number): React.ReactNode => {
    const parts = s.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g)
    return <React.Fragment key={k}>{parts.map((p, i) => {
      if (p.startsWith('`') && p.endsWith('`')) {
        const c = p.slice(1, -1)
        return /^ev:/.test(c) && onRecord ? <code key={i} className="claim-ref" style={{ cursor: 'pointer' }} onClick={() => onRecord(c)}>{c}</code> : <code key={i}>{c}</code>
      }
      if (p.startsWith('**') && p.endsWith('**')) return <b key={i}>{p.slice(2, -2)}</b>
      if (p.length > 2 && p.startsWith('*') && p.endsWith('*')) return <em key={i}>{p.slice(1, -1)}</em>
      return p
    })}</React.Fragment>
  }
  return <>{blocks.map((b, i) => {
    if (b.t === 'h') { const H = `h${Math.min(4, b.level)}` as 'h1'; return <H key={i}>{inline(b.text, 0)}</H> }
    if (b.t === 'ul') return <ul key={i}>{b.items.map((x, j) => <li key={j}>{inline(x, j)}</li>)}</ul>
    if (b.t === 'ol') return <ol key={i}>{b.items.map((x, j) => <li key={j}>{inline(x, j)}</li>)}</ol>
    if (b.t === 'q') return <blockquote key={i}>{inline(b.text, 0)}</blockquote>
    if (b.t === 'pre') return <pre key={i} className="code-box">{b.text}</pre>
    if (b.t === 'table') return (
      <div key={i} style={{ overflowX: 'auto' }}><table><thead><tr>{b.head.map((h, j) => <th key={j}>{inline(h, j)}</th>)}</tr></thead>
        <tbody>{b.rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}>{inline(c, k)}</td>)}</tr>)}</tbody></table></div>)
    if (b.t === 'p') return <p key={i} className={b.tldr ? 'tldr' : ''}>{inline(b.text, 0)}</p>
    return null
  })}</>
}

type Block = { t: 'h'; level: number; text: string } | { t: 'p'; text: string; tldr?: boolean } | { t: 'ul' | 'ol'; items: string[] }
  | { t: 'q'; text: string } | { t: 'pre'; text: string } | { t: 'table'; head: string[]; rows: string[][] }

function parse(md: string): Block[] {
  const out: Block[] = []
  const lines = md.replace(/\r/g, '').split('\n')
  let i = 0, lastH = ''
  const cells = (l: string) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
  while (i < lines.length) {
    const l = lines[i]
    if (!l.trim()) { i++; continue }
    let m
    if (l.startsWith('```')) { const buf: string[] = []; i++; while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++]); i++; out.push({ t: 'pre', text: buf.join('\n') }); continue }
    if ((m = l.match(/^(#{1,6})\s+(.*)$/))) { out.push({ t: 'h', level: m[1].length, text: m[2] }); lastH = m[2].toLowerCase(); i++; continue }
    if (/^\s*\|/.test(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = cells(l); i += 2; const rows: string[][] = []
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]))
      out.push({ t: 'table', head, rows }); continue
    }
    if (/^\s*[-*]\s+/.test(l)) { const items: string[] = []; while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, '')); out.push({ t: 'ul', items }); continue }
    if (/^\s*\d+[.)]\s+/.test(l)) { const items: string[] = []; while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+[.)]\s+/, '')); out.push({ t: 'ol', items }); continue }
    if (l.startsWith('>')) { const buf: string[] = []; while (i < lines.length && lines[i].startsWith('>')) buf.push(lines[i++].replace(/^>\s?/, '')); out.push({ t: 'q', text: buf.join(' ') }); continue }
    const buf: string[] = []
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*[-*]\s+|\s*\d+[.)]\s+|>|```|\s*\|)/.test(lines[i])) buf.push(lines[i++])
    out.push({ t: 'p', text: buf.join(' '), tldr: lastH.startsWith('tl;dr') || lastH === 'summary' })
    lastH = lastH.startsWith('tl;dr') ? 'x' : lastH
  }
  return out
}
