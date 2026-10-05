import React, { useEffect, useState } from 'react'
import { api, post } from '../api'
import { useStore } from '../store'
import type { Snapshot } from '../types'
import { Empty, fmtTime, groupColor, Icon, LevelChip, Panel, Toggle } from '../components/ui'
import { useView } from '../primitives/charts'

export function Control({ s }: { s: Snapshot }) {
  const setSession = useStore((x) => x.setSessionOpen)
  const c = s.control
  if (!c) {
    return (
      <div className="fade-in">
        <div className="page-title">Control</div>
        <section className="hero" style={{ gridTemplateColumns: '1fr', marginTop: 16 }}>
          <div>
            <div className="statement" style={{ fontSize: 24 }}>This session is a historical replay. <em>Nothing here can be steered.</em></div>
            <div className="muted" style={{ maxWidth: 680 }}>
              Control is available when SwarmFrame watches a live swarm: Claude Code agents launched by the runner, or any Claude Code
              session reporting through hooks. Every tool request then passes through the control policy, and you can pause, message,
              interrupt or stop agents, and approve held actions.
            </div>
            <button className="btn accent" style={{ marginTop: 14 }} onClick={() => setSession(true)}>Start a live session</button>
          </div>
        </section>
      </div>
    )
  }
  return <LiveControl s={s} />
}

function LiveControl({ s }: { s: Snapshot }) {
  const c = s.control!
  const data = useView<{ agents: any[] }>('agents_table', { hours: 1 })
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [msg, setMsg] = useState('')
  const [group, setGroup] = useState('')
  const agents = data?.agents ?? []
  const groups = [...new Set(agents.map((a) => a.group).filter(Boolean))]
  const target = (): string[] => (sel.size ? [...sel] : group ? [`group:${group}`] : ['swarm'])
  const act = async (kind: string, payload: Record<string, unknown> = {}) => { for (const t of target()) await api.control(kind, t, payload) }
  return (
    <div className="fade-in">
      <div className="row" style={{ alignItems: 'flex-end', marginBottom: 16 }}>
        <div>
          <div className="page-title">Control</div>
          <div className="muted">{c.agents} agents · {c.simulated ? 'simulated swarm' : c.runner_connected ? 'runner connected' : 'hooks only'} · spent ${c.spent_usd.toFixed(3)}</div>
        </div>
        <div className="row" style={{ marginLeft: 'auto', gap: 10 }}>
          <span className="row" style={{ gap: 6 }}><Icon name="shield" size={16} />Control policy</span>
          <Toggle on={c.policy_enabled} onChange={(v) => post('/api/control/policy', { enabled: v })} />
        </div>
      </div>

      {c.pending.length > 0 && (
        <div className="stack" style={{ marginBottom: 16 }}>
          {c.pending.map((p) => <Pending key={p.id} p={p} />)}
        </div>
      )}

      <div className="grid">
        <Panel title="Agents" className="span-8" kicker={sel.size ? `${sel.size} selected` : group ? `group ${group}` : 'whole swarm'}>
          <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
            <select className="input" style={{ width: 150 }} value={group} onChange={(e) => { setGroup(e.target.value); setSel(new Set()) }}>
              <option value="">all groups</option>{groups.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
            <button className="btn sm" onClick={() => act('pause')}>Pause</button>
            <button className="btn sm" onClick={() => act('resume')}>Resume</button>
            <button className="btn sm" onClick={() => act('interrupt')}>Interrupt</button>
            <button className="btn sm danger" onClick={() => act('kill')}>Stop</button>
            <form className="row" style={{ gap: 6, flex: 1, minWidth: 260 }} onSubmit={(e) => { e.preventDefault(); if (msg) { act('message', { text: msg }); setMsg('') } }}>
              <input className="input" placeholder="Message the selected agents…" value={msg} onChange={(e) => setMsg(e.target.value)} />
              <button className="btn sm" type="submit">Send</button>
            </form>
          </div>
          {!agents.length ? <Empty title="No agents have reported yet." /> : (
            <div style={{ maxHeight: 520, overflow: 'auto' }}>
              <table className="t">
                <thead><tr><th style={{ width: 24 }} /><th>Agent</th><th>Group</th><th>Status</th><th>Working on</th><th className="num">Events</th><th className="num">Tools</th><th>Last</th></tr></thead>
                <tbody>
                  {agents.map((a) => (
                    <tr key={a.id}>
                      <td><input type="checkbox" checked={sel.has(a.id)} onChange={(e) => { const n = new Set(sel); e.target.checked ? n.add(a.id) : n.delete(a.id); setSel(n) }} /></td>
                      <td><button className="claim-ref" onClick={() => useStore.getState().openDrawer({ kind: 'entity', id: a.id })}>{a.label}</button></td>
                      <td><span className="row" style={{ gap: 6 }}><i style={{ width: 8, height: 8, borderRadius: 2, background: groupColor(a.group), display: 'inline-block' }} />{a.group}</span></td>
                      <td className="mono" style={{ color: a.status === 'running' ? 'var(--st-observed)' : a.status === 'paused' ? 'var(--st-inferred)' : a.status === 'killed' ? 'var(--st-contradicted)' : 'var(--ink-3)' }}>{a.status}{a.pending ? ' · waiting' : ''}</td>
                      <td className="muted">{a.family}</td>
                      <td className="num">{a.events}</td>
                      <td className="num">{a.tool_calls ?? '—'}</td>
                      <td className="mono muted">{fmtTime(a.last)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <Panel title="Operator log" className="span-4">
          {!c.actions.length ? <Empty title="No operator actions yet." /> : [...c.actions].reverse().map((a) => (
            <div key={a.id} className="list-item">
              <div className="row" style={{ justifyContent: 'space-between' }}><span className="chip soft" style={{ color: 'var(--accent)' }}>{a.kind}</span><span className="mono muted">{fmtTime(a.ts)}</span></div>
              <div style={{ fontSize: 13, marginTop: 3 }}>{a.result}</div>
            </div>
          ))}
          <hr className="soft" />
          <div className="label" style={{ marginBottom: 6 }}>Connect any Claude Code session</div>
          <div className="muted" style={{ fontSize: 12.5 }}>Add hooks to <span className="mono">.claude/settings.json</span> that POST each hook payload to <span className="mono">{location.origin}/ingest/claude-code</span>. See README.</div>
        </Panel>
      </div>
    </div>
  )
}

function Pending({ p }: { p: NonNullable<Snapshot['control']>['pending'][number] }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t) }, [])
  const started = new Date(p.ts.endsWith('Z') ? p.ts : p.ts + 'Z').getTime()
  const left = Math.max(0, Math.round(p.timeout_s - (now - started) / 1000))
  return (
    <div className="card row" style={{ borderColor: 'var(--lv-alert)', padding: 14, gap: 14 }}>
      <LevelChip level="ALERT" />
      <div style={{ flex: 1 }}>
        <div><b>{p.label}</b> wants to run <span className="mono">{p.tool}</span></div>
        <div className="mono" style={{ color: 'var(--ink-2)', marginTop: 2 }}>{p.input}</div>
      </div>
      <span className="mono muted">{left}s, then {p.default}</span>
      <button className="btn" onClick={() => api.control('allow', p.id)}>Allow</button>
      <button className="btn danger" onClick={() => api.control('deny', p.id)}>Deny</button>
    </div>
  )
}
