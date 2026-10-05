import React from 'react'
import { post } from '../api'
import { useStore } from '../store'
import type { Cite, FindingRow, Severity } from '../types'
import { EVIDENCE, SEVERITY } from '../words'
import { Menu, Tip } from './kit'
import { fmtTime, Icon } from './ui'

const CITE_KIND: Record<string, string> = { claim: 'claim', event: 'recorded event', entity: '' }
const citeTitle = (c: Cite) => `[${c.n}] ${c.kind === 'claim' ? `${(c.status ?? '').toLowerCase()} claim: ` : c.kind === 'event' ? `${fmtTime(c.ts)} · ` : ''}${c.label}`
export const openCite = (c: Cite) => useStore.getState().openDrawer({ kind: c.kind, id: c.id } as any)

/** Inline numbered source marks: [1][2][3] +2. Each opens its evidence. */
export function CiteMarks({ cites, max = 4, label }: { cites?: Cite[]; max?: number; label?: string }) {
  if (!cites?.length) return null
  return (
    <span className="cites" onClick={(e) => e.stopPropagation()}>
      {label && <span className="cites-l">{label}</span>}
      {cites.slice(0, max).map((c) => (
        <button key={c.id} className={`cite-mark k-${c.kind} ${c.status ? 'st-' + c.status : ''}`} title={citeTitle(c)}
          aria-label={`Source ${c.n}: ${CITE_KIND[c.kind]} ${c.label}`} onClick={() => openCite(c)}>{c.n}</button>
      ))}
      {cites.length > max && <span className="cites-more">+{cites.length - max}</span>}
    </span>
  )
}

/** The numbered source list under a finding or an answer. */
export function SourceList({ cites }: { cites: Cite[] }) {
  return (
    <ol className="source-list">
      {cites.map((c) => (
        <li key={c.id} className={`k-${c.kind}`} onClick={() => openCite(c)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') openCite(c) }}>
          <span className="cite-mark">{c.n}</span>
          <span className="src-kind mono">{c.kind === 'claim' ? (c.status ?? 'claim').toLowerCase() : c.kind === 'event' ? fmtTime(c.ts) : c.type ?? 'entity'}</span>
          <span className="src-label">{c.label}</span>
        </li>
      ))}
    </ol>
  )
}

export async function findingAction(id: string, action: string, label?: string, level?: string) {
  try {
    await post(`/api/incident/${encodeURIComponent(id)}/action`, action === 'escalate' ? { action, level: level ?? 'ALERT' } : { action })
    const msg: Record<string, string> = {
      investigate: 'Investigation requested', watch: 'Watching more closely', dismiss: 'Dismissed',
      pin: 'Pinned to the top', unpin: 'Unpinned', snooze: 'Snoozed', unsnooze: 'Back on the list', ack: 'Acknowledged', escalate: 'Escalated', lower: 'Lowered' }
    useStore.getState().showToast(`${msg[action] ?? 'Done'}${label ? `: ${label}` : ''}`)
  } catch (e: any) {
    useStore.getState().showToast(String(e.message || e))
  }
}

export function SevMark({ sev }: { sev: Severity }) {
  const s = SEVERITY[sev]
  return <Tip text={s.help}><span className={`sev sev-${sev}`}><i />{s.label}</span></Tip>
}

export function EvidenceChip({ kind }: { kind: string }) {
  const e = EVIDENCE[kind] ?? EVIDENCE.inferred
  return <Tip text={e.help}><span className="ev-chip" style={{ color: e.color }}><span className="dot" />{e.label}</span></Tip>
}

export function FindingItem({ f, compact = false }: { f: FindingRow; compact?: boolean }) {
  const open = useStore((x) => x.openDrawer)
  const select = useStore((x) => x.selectInvestigation)
  const go = () => open({ kind: 'finding', id: f.id })
  const primary = f.investigation && f.action === 'investigation'
    ? { label: f.investigation_status === 'running' || f.investigation_status === 'open' ? 'Open investigation' : 'Read finding', run: () => select(f.investigation!) }
    : f.group ? { label: `See all ${f.count}`, run: go }
      : { label: 'Investigate', run: () => findingAction(f.id, 'investigate') }
  return (
    <div className={`finding sevrow-${f.severity} ${compact ? 'compact' : ''}`} onClick={go} role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter') go() }}>
      <div className="finding-sev"><SevMark sev={f.severity} /></div>
      <div className="finding-main">
        <div className="finding-head">
          {f.pinned && <Icon name="pin" size={13} />}
          <span className="finding-title">{f.headline}</span>
          {f.overdue && <span className="chip soft lv-ALERT" title="An escalation nobody has acknowledged within the agreed time"><span className="dot" />overdue</span>}
          {!f.overdue && f.needs_ack && <span className="chip soft" title="Escalated by the team; waiting for a person to take receipt">awaiting your receipt</span>}
          {f.pending_level && <span className="chip soft" title={f.history?.slice().reverse().find((h) => h.held)?.held ?? ''}>held: wants {f.pending_level.toLowerCase()}</span>}
        </div>
        {f.detail && !compact && <div className="finding-detail">{f.detail}</div>}
        {!f.detail && !compact && f.explain?.what && f.explain.what !== f.headline && <div className="finding-detail plain">{f.explain.what}</div>}
        <div className="finding-next"><span className="next-k">Next</span>{f.next}</div>
        {(f.cites?.length ?? 0) > 0 && <div className="finding-cites"><CiteMarks cites={f.cites} max={compact ? 4 : 6} label="sources" /></div>}
      </div>
      <div className="finding-meta">
        <span className={`fresh fresh-${f.fresh}`}>{f.fresh_text}</span>
        {!compact && <EvidenceChip kind={f.evidence} />}
      </div>
      {!compact && (
        <div className="finding-actions" onClick={(e) => e.stopPropagation()}>
          <button className="btn sm" onClick={primary.run}>{primary.label}</button>
          <Menu label="" icon="more" variant="sm ghost" items={[
            { label: 'Open details', icon: 'eye', onClick: go },
            { label: 'Show me in the World', icon: 'globe', onClick: () => useStore.getState().showInWorld(f.scope) },
            { label: 'Investigate', icon: 'investigations', onClick: () => findingAction(f.id, 'investigate'), disabled: f.investigation_status === 'running' },
            { label: 'Watch more closely', icon: 'attention', onClick: () => findingAction(f.id, 'watch') },
            ...(f.needs_ack ? [{ label: 'Acknowledge', icon: 'check', hint: 'take receipt of this escalation', onClick: () => findingAction(f.id, 'ack', f.headline) }] : []),
            ...(f.level !== 'PAGE' && !f.group ? [{ label: f.level === 'ALERT' ? 'Escalate to act now' : 'Escalate to act', icon: 'flag', onClick: () => findingAction(f.id, 'escalate', f.headline) }] : []),
            { sep: true, label: '' },
            { label: f.pinned ? 'Unpin' : 'Pin to the top', icon: 'pin', onClick: () => findingAction(f.id, f.pinned ? 'unpin' : 'pin') },
            { label: 'Snooze', icon: 'snooze', hint: 'hide from the Brief', onClick: () => findingAction(f.id, 'snooze') },
            { label: f.group ? `Dismiss all ${f.count}` : 'Dismiss', icon: 'x', danger: true, onClick: () => findingAction(f.id, 'dismiss') },
          ]} />
        </div>
      )}
    </div>
  )
}

export function FindingList({ items, compact = false, empty }: { items: FindingRow[]; compact?: boolean; empty?: React.ReactNode }) {
  if (!items.length) return <>{empty ?? null}</>
  return <div className="findings">{items.map((f) => <FindingItem key={f.id} f={f} compact={compact} />)}</div>
}

export const SEV_ORDER: Severity[] = ['ACT', 'LOOK', 'WATCH']
export const atLeast = (s: Severity, min: Severity) => SEV_ORDER.indexOf(s) <= SEV_ORDER.indexOf(min)
