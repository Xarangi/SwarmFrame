import React, { useEffect, useRef, useState } from 'react'
import { post } from '../api'
import { useStore } from '../store'
import type { DashState, Snapshot } from '../types'
import { DEFAULT_TERMS, help, term, Terms } from '../words'
import { Icon } from './ui'

/* ------------------------------------------------------------------ the source's nouns */
export function useTerms(): Terms {
  const t = useStore((x) => x.snap?.brief?.terms)
  const spec = useStore((x) => x.dash?.spec.terminology)
  return { agent: spec?.agent || t?.agent || DEFAULT_TERMS.agent, resource: spec?.resource || t?.resource || DEFAULT_TERMS.resource }
}

/* ------------------------------------------------------------------ hover help */
export function Tip({ text, children, inline = true }: { text: string; children: React.ReactNode; inline?: boolean }) {
  if (!text) return <>{children}</>
  return <span className={`tip ${inline ? 'inline' : ''}`} data-tip={text} tabIndex={0}>{children}</span>
}

/** A glossary term: the plain label, with its explanation on hover. */
export function Term({ k, children }: { k: string; children?: React.ReactNode }) {
  const t = useTerms()
  return <Tip text={help(k, t)}><span className="term">{children ?? term(k, t)}</span></Tip>
}

/* ------------------------------------------------------------------ dropdown menu */
export interface MenuItem { label: string; icon?: string; onClick?: () => void; hint?: string; disabled?: boolean; sep?: boolean; danger?: boolean }

export function Menu({ label, icon = 'edit', items, align = 'right', variant = '' }: {
  label: React.ReactNode; icon?: string; items: MenuItem[]; align?: 'left' | 'right'; variant?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('mousedown', off); window.addEventListener('keydown', esc)
    return () => { window.removeEventListener('mousedown', off); window.removeEventListener('keydown', esc) }
  }, [open])
  return (
    <div className="menu-wrap" ref={ref}>
      <button className={`btn ${variant} ${open ? 'pressed' : ''}`} onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open}>
        {icon && <Icon name={icon} size={15} />}{label}{label ? <Icon name="down" size={13} /> : null}
      </button>
      {open && (
        <div className={`menu ${align}`} role="menu">
          {items.map((it, i) => it.sep
            ? <div key={i} className="menu-sep" />
            : (
              <button key={i} role="menuitem" className={`menu-item ${it.danger ? 'danger' : ''}`} disabled={it.disabled}
                onClick={() => { setOpen(false); it.onClick?.() }}>
                {it.icon ? <Icon name={it.icon} size={15} /> : <span style={{ width: 15 }} />}
                <span className="menu-text"><span>{it.label}</span>{it.hint && <span className="menu-hint">{it.hint}</span>}</span>
              </button>
            ))}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ edits: apply at once, undo from the toast */
export async function dashOps(ops: Record<string, any>[], rationale = '', toast?: string): Promise<DashState | null> {
  try {
    const d = await post<DashState>('/api/dashboard/ops', { ops, rationale, by: 'human' })
    useStore.getState().setDash(d)
    if (toast) useStore.getState().showToast(toast, true)
    return d
  } catch (e: any) {
    useStore.getState().showToast(String(e.message || e).replace(/^\d+ /, '').replace(/^\{"detail":"(.*)"\}$/, '$1'))
    return null
  }
}

export async function undoLast() {
  try {
    useStore.getState().setDash(await post<DashState>('/api/dashboard/undo'))
    useStore.getState().showToast('Undone')
  } catch { useStore.getState().showToast('Nothing to undo') }
}

export function ToastHost() {
  const t = useStore((x) => x.toast)
  if (!t) return null
  return (
    <div className="toast" role="status" key={t.id}>
      <span>{t.text}</span>
      {t.undo && <button className="toast-btn" onClick={() => { useStore.setState({ toast: null }); undoLast() }}><Icon name="undo" size={14} />Undo</button>}
      <button className="toast-x" aria-label="Dismiss" onClick={() => useStore.setState({ toast: null })}><Icon name="x" size={13} /></button>
    </div>
  )
}

/* ------------------------------------------------------------------ capabilities of the current source */
export function hasCap(s: Snapshot | null, caps: Record<string, { present: boolean }> | undefined, c: string): boolean {
  if (c === 'control') return !!s?.control
  return !!caps?.[c]?.present
}
