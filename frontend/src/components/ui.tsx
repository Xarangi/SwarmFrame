import React from 'react'
import { useStore } from '../store'
import type { Claim, ClaimStatus, Level } from '../types'

/* ---------------------------------------------------------------- color: entity-stable, never rank */
const FIXED: Record<string, number> = {
  chat: 5, research: 2, docs: 1, code: 6, mail: 3, sheets: 8, social: 7, media: 4,
  files: 1, shell: 6, search: 2, web: 3, delegation: 4, planning: 8, narration: 7,
}
export function famColor(f: string | null | undefined): string {
  const i = f ? FIXED[f] : undefined
  return i ? `var(--c${i})` : 'var(--c-other)'
}
const GROUPS: Record<string, number> = {}
export function groupColor(g: string | null | undefined): string {
  if (!g) return 'var(--c-other)'
  if (!(g in GROUPS)) {
    const n = Object.keys(GROUPS).length
    GROUPS[g] = n < 8 ? [2, 1, 5, 4, 6, 3, 7, 8][n] : 0
  }
  return GROUPS[g] ? `var(--c${GROUPS[g]})` : 'var(--c-other)'
}

/* ---------------------------------------------------------------- time */
export function fmtTime(ts: string | null | undefined, withDate = false): string {
  if (!ts) return '—'
  const d = new Date(ts.endsWith('Z') || ts.includes('+') ? ts : ts + 'Z')
  const hm = d.toISOString().slice(11, 16)
  return withDate ? `${d.toISOString().slice(5, 10)} ${hm}` : hm
}
export function fmtDate(ts: string | null | undefined): string {
  if (!ts) return '—'
  const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
}
/** Axis label sized to the span shown: years → "Mar 2025", weeks → "Mar 14", hours → "14:05". */
export function fmtTick(t: Date, spanMs: number): string {
  const day = 86400e3
  if (spanMs > 400 * day) return t.toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
  if (spanMs > 3 * day) return t.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
  return t.toISOString().slice(11, 16)
}
/** A date with the year when it is not obvious (data spanning years, or not this year). */
export function fmtDay(ts: string | null | undefined, withYear = false): string {
  if (!ts) return '—'
  const d = new Date(ts.endsWith('Z') || ts.includes('+') ? ts : ts + 'Z')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', ...(withYear ? { year: 'numeric' } : {}), timeZone: 'UTC' })
}
export const fmtNum = (n: number) => (n >= 10000 ? `${(n / 1000).toFixed(0)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${Math.round(n)}`)
export const pct = (x: number) => `${Math.round(x * 100)}%`

/* ---------------------------------------------------------------- chips */
const ST_LABEL: Record<ClaimStatus, string> = {
  OBSERVED: 'Observed', DERIVED: 'Derived', SELF_REPORTED: 'Self-reported', INFERRED: 'Inferred',
  CONTRADICTED: 'Contradicted', UNKNOWN: 'Unknown',
}
export function StatusChip({ status, soft = true }: { status: ClaimStatus; soft?: boolean }) {
  return <span className={`chip ${soft ? 'soft' : ''} st-${status}`}><span className="dot" />{ST_LABEL[status]}</span>
}
/* Monitor escalation levels, shown in the same three words as findings. */
const LEVEL_WORD: Record<string, [string, string]> = {
  WATCH: ['watch', 'Being watched; no action needed unless it grows.'],
  INVESTIGATE: ['look', 'Worth a look: an investigation may be running.'],
  ALERT: ['act', 'Needs a decision.'], PAGE: ['act now', 'Needs a decision now.'],
}
export function LevelChip({ level }: { level: Level | string }) {
  if (!level || level === 'NONE' || level === 'INFO') return null
  const [w, h] = LEVEL_WORD[String(level)] ?? [String(level).toLowerCase(), '']
  return <span className={`chip soft lv-${level}`} title={h}><span className="dot" />{w}</span>
}
const KIND_WORD: Record<string, string> = { NEW: 'new', UPDATE: 'updated', REVISED: 'revised assessment', STATUS: 'status', CONTROL: 'control', HUMAN: 'you' }
export function KindChip({ kind }: { kind: string }) {
  const color = kind === 'NEW' ? 'var(--accent)' : kind === 'REVISED' ? 'var(--st-self)' : kind === 'UPDATE' ? 'var(--st-derived)'
    : 'var(--ink-3)'
  return <span className="chip" style={{ color, borderColor: 'transparent', padding: 0 }}>{KIND_WORD[kind] ?? kind.toLowerCase()}</span>
}

/* ---------------------------------------------------------------- claims */
export function ClaimLink({ claim, children }: { claim: Claim; children?: React.ReactNode }) {
  const open = useStore((s) => s.openDrawer)
  return (
    <button className={`claim-ref st-${claim.status}`} title={`${ST_LABEL[claim.status]} · click for evidence`}
      onClick={(e) => { e.stopPropagation(); open({ kind: 'claim', id: claim.id }) }}>
      <span style={{ color: 'var(--ink)' }}>{children ?? claim.statement}</span>
    </button>
  )
}

export function ClaimList({ ids, claims, compact = false }: { ids: string[]; claims: Record<string, Claim>; compact?: boolean }) {
  const open = useStore((s) => s.openDrawer)
  const list = ids.map((i) => claims[i]).filter(Boolean)
  if (!list.length) return null
  return (
    <div className="stack" style={{ gap: compact ? 4 : 6 }}>
      {list.map((c) => (
        <div key={c.id} className="row clickable" style={{ alignItems: 'flex-start', gap: 8, padding: '3px 4px', borderRadius: 6 }}
          onClick={() => open({ kind: 'claim', id: c.id })}>
          <div style={{ paddingTop: 2 }}><StatusChip status={c.status} /></div>
          <div style={{ fontSize: compact ? 12.5 : 13.5, color: 'var(--ink-2)', flex: 1 }}>{c.statement}</div>
          <span className="mono muted">{c.support.length ? `${c.support.length} ev` : ''}</span>
        </div>
      ))}
    </div>
  )
}

/* ---------------------------------------------------------------- frames */
export function Panel({ title, kicker, children, className = '', right, style }: {
  title: React.ReactNode; kicker?: React.ReactNode; children: React.ReactNode; className?: string; right?: React.ReactNode
  style?: React.CSSProperties
}) {
  return (
    <section className={`panel ${className}`} style={style}>
      <div className="panel-head">
        <span className="title">{title}</span>
        {kicker && <span className="label">{kicker}</span>}
        {right && <span style={{ marginLeft: 'auto' }}>{right}</span>}
      </div>
      <div className="panel-body">{children}</div>
    </section>
  )
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return <div className="empty"><span className="serif">{title}</span><span style={{ fontSize: 12.5 }}>{children}</span></div>
}

export function Seg<T extends string>({ value, options, onChange }: { value: T; options: { v: T; l: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="seg">
      {options.map((o) => <button key={o.v} className={o.v === value ? 'on' : ''} onClick={() => onChange(o.v)}>{o.l}</button>)}
    </div>
  )
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label?: string }) {
  return <button className={`toggle ${on ? 'on' : ''}`} aria-label={label} aria-pressed={on} onClick={() => onChange(!on)} />
}

export function Bar({ value, max = 1, color = 'var(--accent)' }: { value: number; max?: number; color?: string }) {
  return <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.max(2, (value / (max || 1)) * 100)}%`, background: color }} /></div>
}

export function ScopeLink({ scope, label }: { scope: string | null; label?: string }) {
  const open = useStore((s) => s.openDrawer)
  const known = useStore((s) => (scope ? s.snap?.scope_labels?.[scope] : undefined))
  if (!scope) return null
  label = label ?? known
  const [kind, id] = scope.includes(':') ? [scope.slice(0, scope.indexOf(':')), scope.slice(scope.indexOf(':') + 1)] : ['', scope]
  const clickable = kind === 'agent' || kind === 'resource' || kind === 'actor'
  return clickable
    ? <button className="claim-ref" style={{ color: 'var(--ink)' }} onClick={() => open({ kind: 'entity', id })}>{label ?? id}</button>
    : <span>{label ?? scope}</span>
}

/* ---------------------------------------------------------------- icons (1.6px line, 18px) */
const P = (d: string) => <path d={d} />
const ICONS: Record<string, React.ReactNode> = {
  org: <><circle cx="12" cy="5" r="2.4" /><circle cx="5" cy="19" r="2.4" /><circle cx="12" cy="19" r="2.4" /><circle cx="19" cy="19" r="2.4" />{P('M12 7.4v9.2')}{P('M12 11H5v5.6')}{P('M12 11h7v5.6')}</>,
  chat: <>{P('M4 5h16v11H9l-5 4V5Z')}{P('M8 9.5h8')}{P('M8 12.5h5')}</>,
  room: <>{P('M3 12a9 9 0 1 0 18 0 9 9 0 0 0-18 0')}{P('M12 7v5l3 2')}</>,
  investigations: <>{P('M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13')}{P('M15.5 15.5 21 21')}</>,
  attention: <>{P('M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12Z')}<circle cx="12" cy="12" r="2.8" /></>,
  control: <>{P('M4 6h10')}{P('M18 6h2')}<circle cx="16" cy="6" r="2" />{P('M4 12h4')}{P('M12 12h8')}<circle cx="10" cy="12" r="2" />{P('M4 18h12')}<circle cx="18" cy="18" r="2" /></>,
  configure: <>{P('M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z')}{P('M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z')}</>,
  evaluate: <>{P('M4 20V10')}{P('M10 20V4')}{P('M16 20v-7')}{P('M22 20H2')}</>,
  play: <>{P('M7 4.5v15l12-7.5-12-7.5Z')}</>,
  pause: <>{P('M8 5v14')}{P('M16 5v14')}</>,
  step: <>{P('M6 5v14l9-7-9-7Z')}{P('M18 5v14')}</>,
  plus: <>{P('M12 5v14')}{P('M5 12h14')}</>,
  x: <>{P('M6 6l12 12')}{P('M18 6 6 18')}</>,
  layers: <>{P('m12 3 9 5-9 5-9-5 9-5Z')}{P('m3 13 9 5 9-5')}</>,
  pin: <>{P('M9 4h6l-1 6 4 3H6l4-3-1-6Z')}{P('M12 13v8')}</>,
  arrow: <>{P('M5 12h14')}{P('m13 6 6 6-6 6')}</>,
  grip: <>{[6, 12, 18].map((y) => <React.Fragment key={y}><circle cx="9" cy={y} r="1" /><circle cx="15" cy={y} r="1" /></React.Fragment>)}</>,
  sun: <><circle cx="12" cy="12" r="4" />{P('M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4')}</>,
  moon: <>{P('M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z')}</>,
  shield: <>{P('M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3Z')}</>,
  globe: <><circle cx="12" cy="12" r="9" />{P('M3 12h18')}{P('M12 3c2.8 3 2.8 15 0 18')}{P('M12 3c-2.8 3-2.8 15 0 18')}</>,
  home: <>{P('M4 11.5 12 5l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1v-8.5Z')}</>,
  flag: <>{P('M5 21V4')}{P('M5 4h11l-2 4 2 4H5')}</>,
  activity: <>{P('M3 12h4l3-7 4 14 3-7h4')}</>,
  hood: <><circle cx="12" cy="12" r="3" />{P('M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1')}</>,
  edit: <>{P('M4 20h4L19 9l-4-4L4 16v4Z')}{P('m13.5 6.5 4 4')}</>,
  more: <><circle cx="5" cy="12" r="1.3" /><circle cx="12" cy="12" r="1.3" /><circle cx="19" cy="12" r="1.3" /></>,
  chevron: <>{P('m9 6 6 6-6 6')}</>,
  down: <>{P('m6 9 6 6 6-6')}</>,
  undo: <>{P('M9 14 4 9l5-5')}{P('M4 9h10a6 6 0 0 1 0 12h-3')}</>,
  lens: <>{P('M6 3h12v18l-6-4-6 4V3Z')}</>,
  check: <>{P('m5 12.5 4.5 4.5L19 7')}</>,
  eye: <>{P('M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12Z')}<circle cx="12" cy="12" r="2.8" /></>,
  clock: <><circle cx="12" cy="12" r="9" />{P('M12 7v5l3 2')}</>,
  snooze: <>{P('M4 4h6l-6 7h6')}{P('M13 12h7l-7 8h7')}</>,
  spark: <>{P('M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6')}</>,
  file: <>{P('M6 3h8l4 4v14H6V3Z')}{P('M14 3v4h4')}{P('M9 12h6M9 16h6')}</>,
  palette: <>{P('M12 3a9 9 0 1 0 0 18c1.2 0 1.8-.8 1.8-1.7 0-.5-.2-.9-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1 .8-1.7 1.7-1.7H17a4 4 0 0 0 4-4C21 6.5 17 3 12 3Z')}<circle cx="7.5" cy="11" r="1.2" /><circle cx="10.5" cy="7" r="1.2" /><circle cx="15" cy="7.5" r="1.2" /></>,
  upload: <>{P('M12 16V4')}{P('m7 9 5-5 5 5')}{P('M4 16v4h16v-4')}</>,
  download: <>{P('M12 4v12')}{P('m7 11 5 5 5-5')}{P('M4 20h16')}</>,
}
export function Icon({ name, size = 18, stroke = 1.6 }: { name: string; size?: number; stroke?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden>{ICONS[name]}</svg>
  )
}

export function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className="logo">
      <circle cx="16" cy="16" r="12.5" fill="none" stroke="currentColor" strokeWidth="1.6" opacity=".9" />
      <path d="M16 1.5v5M16 25.5v5M1.5 16h5M25.5 16h5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="12.2" cy="13.4" r="1.6" fill="currentColor" opacity=".55" />
      <circle cx="18.6" cy="11.6" r="1.35" fill="currentColor" opacity=".55" />
      <circle cx="11.8" cy="19.6" r="1.25" fill="currentColor" opacity=".55" />
      <circle cx="20.4" cy="19.2" r="1.5" fill="currentColor" opacity=".55" />
      <circle cx="16.4" cy="16.2" r="2.6" fill="var(--accent)" />
    </svg>
  )
}
