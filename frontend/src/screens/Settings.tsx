import React, { useEffect, useState } from 'react'
import { post } from '../api'
import { useStore } from '../store'
import type { DashState, Snapshot } from '../types'
import { Icon, Toggle } from '../components/ui'
import { dashOps } from '../components/kit'
import { Configure } from './Configure'
import { Evaluate } from './Evaluate'
import { Appearance } from '../components/Appearance'

export async function lensAction(action: string, name: string, new_name = '') {
  try {
    useStore.getState().setDash(await post<DashState>('/api/dashboard/lens', { action, name, new_name }))
    const msg: Record<string, string> = { save: `Saved and switched to “${name}”`, switch: `Switched to “${name}”`, delete: `Deleted “${name}”`, rename: `Renamed to “${new_name}”` }
    useStore.getState().showToast(msg[action] ?? 'Done')
    return true
  } catch (e: any) {
    useStore.getState().showToast(String(e.message || e).replace(/^\d+ /, ''))
    return false
  }
}

type Tab = 'appearance' | 'dashboard' | 'monitoring' | 'compare'

export function Settings({ s }: { s: Snapshot }) {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem('ss.settingsTab') as Tab) || 'appearance')
  return (
    <div className="fade-in">
      <header className="page-head"><div><h1 className="page-title">Settings</h1>
        <p className="page-sub">{s.source.title} · {s.org.name}</p></div></header>
      <div className="studio-tabs flush">
        {([['appearance', 'Look'], ['dashboard', 'Lenses and words'], ['monitoring', 'Monitoring and models'], ['compare', 'Compare strategies']] as [Tab, string][]).map(([k, l]) =>
          <button key={k} className={tab === k ? 'on' : ''} onClick={() => { setTab(k); localStorage.setItem('ss.settingsTab', k) }}>{l}</button>)}
      </div>
      <div className="embedded" style={{ marginTop: 18 }}>
        {tab === 'appearance' && <Appearance />}
        {tab === 'dashboard' && <DashboardSettings />}
        {tab === 'monitoring' && <Configure s={s} />}
        {tab === 'compare' && <Evaluate />}
      </div>
    </div>
  )
}

function DashboardSettings() {
  const dash = useStore((x) => x.dash)
  const [name, setName] = useState('')
  const [terms, setTerms] = useState<{ agent: string; resource: string }>({ agent: '', resource: '' })
  useEffect(() => { if (dash) setTerms({ agent: dash.spec.terminology.agent ?? '', resource: dash.spec.terminology.resource ?? '' }) }, [dash?.spec.version]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!dash) return null
  return (
    <div className="settings-grid">
      <section className="panel"><div className="panel-head"><span className="title">Lenses</span><span className="label kicker">saved layouts per scenario</span></div>
        <div className="panel-body stack">
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>Watch the same swarm differently during an incident, a quiet week or a report. Each lens keeps its own pages, Brief and history.</p>
          {dash.lenses.map((l) => <LensRow key={l} name={l} current={l === dash.lens} only={dash.lenses.length === 1} />)}
          <form className="row" onSubmit={async (e) => { e.preventDefault(); if (name.trim() && await lensAction('save', name.trim())) setName('') }}>
            <input className="input" placeholder="e.g. Incident review" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn" type="submit" disabled={!name.trim()}><Icon name="lens" size={14} />Save</button>
          </form>
        </div>
      </section>
      <section className="panel"><div className="panel-head"><span className="title">Words</span><span className="label kicker">what to call things</span></div>
        <div className="panel-body stack">
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>Labels across the dashboard use these nouns.</p>
          <form className="stack" onSubmit={(e) => { e.preventDefault(); dashOps([{ op: 'set_terminology', terms: { agent: terms.agent || 'agent', resource: terms.resource || 'resource' } }], 'set terminology', 'Updated the words') }}>
            <label className="field"><span className="label">Each actor is a…</span><input className="input" value={terms.agent} placeholder="agent" onChange={(e) => setTerms({ ...terms, agent: e.target.value })} /></label>
            <label className="field"><span className="label">What they act on is a…</span><input className="input" value={terms.resource} placeholder="resource" onChange={(e) => setTerms({ ...terms, resource: e.target.value })} /></label>
            <div><button className="btn" type="submit">Save words</button></div>
          </form>
        </div>
      </section>
      <section className="panel"><div className="panel-head"><span className="title">Display</span></div>
        <div className="panel-body stack">
          <label className="row" style={{ gap: 10 }}>
            <Toggle on={dash.spec.machinery} onChange={(v) => dashOps([{ op: 'set_machinery', on: v }], v ? 'showed the machinery' : 'hid the machinery', v ? 'Added “The machinery” under Activity' : 'Removed “The machinery”')} />
            <span><b>Show the machinery</b><br /><span className="muted" style={{ fontSize: 12.5 }}>The reading plan, groups, coverage and analyst team as full panels on a page, for the level of detail an operator of SwarmFrame wants.</span></span>
          </label>
        </div>
      </section>
    </div>
  )
}

function LensRow({ name, current, only }: { name: string; current: boolean; only: boolean }) {
  const [renaming, setRenaming] = useState(false)
  const [v, setV] = useState(name)
  return (
    <div className={`lens-row ${current ? 'on' : ''}`}>
      <Icon name="lens" size={14} />
      {renaming
        ? <form style={{ flex: 1 }} onSubmit={async (e) => { e.preventDefault(); if (v.trim() && v !== name) await lensAction('rename', name, v.trim()); setRenaming(false) }}>
          <input className="input" autoFocus value={v} onChange={(e) => setV(e.target.value)} onBlur={() => setRenaming(false)} /></form>
        : <span style={{ flex: 1, fontWeight: current ? 600 : 500 }}>{name}{current && <span className="mono muted"> · in use</span>}</span>}
      {!current && <button className="btn sm" onClick={() => lensAction('switch', name)}>Use</button>}
      <button className="btn sm ghost" onClick={() => setRenaming(true)}>Rename</button>
      {!only && <button className="btn sm ghost danger" onClick={() => { if (window.confirm(`Delete the lens "${name}"? Its pages and history go with it.`)) lensAction('delete', name) }}>Delete</button>}
    </div>
  )
}
