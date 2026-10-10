import React, { useEffect, useRef, useState } from 'react'
import { get, post } from '../api'
import { ChatMsg, useStore } from '../store'
import { fmtTime, Icon } from './ui'
import { Menu } from './kit'
import { CiteMarks, openCite, SourceList } from './findings'
import { StudyGuide } from '../screens/Compose'
import type { Cite } from '../types'

interface ChatState {
  messages: ChatMsg[]; target: 'copilot' | 'channel'
  watch: { on: boolean; levels: string[]; kinds: string[]; min_interval_s: number }
  narrate?: { on: boolean; every_s: number }; commentary?: { on: boolean; every_s: number }
  channel: { connected: boolean; since: string | null; command: string; mcp_json: string }
  copilot: { mode: string; busy: boolean; turns: number; cost_usd: number; model: string | null }
}

const SUGGEST = ['What needs my attention right now?', 'What changed in the last hour?',
  'Which division is the analyst organization least sure about?', 'Focus the monitors on the busiest shared resource']

/** Turn claim ids in agent text into numbered source marks (matching the list under the answer). */
function Rich({ text, cites = [] }: { text: string; cites?: Cite[] }) {
  const open = useStore((s) => s.openDrawer)
  const parts = text.split(/(\s*\(?(?:clm_[0-9a-f]{10}|ev:[A-Za-z0-9:_-]{6,80})\)?)/g)
  return <>{parts.map((p, i) => {
    const id = p.match(/clm_[0-9a-f]{10}|ev:[A-Za-z0-9:_-]{6,80}/)?.[0]
    if (!id) return <React.Fragment key={i}>{p}</React.Fragment>
    const c = cites.find((x) => x.id === id)
    return c ? <button key={i} className={`cite-mark sup k-${c.kind} ${c.status ? 'st-' + c.status : ''}`} title={`[${c.n}] ${c.label}`} onClick={() => openCite(c)}>{c.n}</button>
      : <button key={i} className="cite-mark sup unknown" title="This claim id is not known at the current replay time" onClick={() => open({ kind: id.startsWith('ev:') ? 'event' : 'claim', id } as any)}>?</button>
  })}</>
}

export function ChatDock({ docked = false }: { docked?: boolean }) {
  const { chat, setChat, chatOpen, setChatOpen, typing } = useStore()
  const [st, setSt] = useState<ChatState | null>(null)
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const tick = useStore((s) => s.tick)
  const load = () => get<ChatState>('/api/chat').then((d) => { setSt(d); setChat(d.messages) }).catch(() => {})
  const sid = useStore((s) => s.snap?.session_id)
  useEffect(() => { load() }, [sid])                   // a new session starts a clean live column
  useEffect(() => { if (chatOpen && tick % 5 === 0) get<ChatState>('/api/chat').then(setSt).catch(() => {}) }, [tick, chatOpen])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [chat.length, chatOpen, typing])
  const draft = useStore((s) => s.chatDraft)
  useEffect(() => { if (draft) { setText(draft); useStore.setState({ chatDraft: '' }) } }, [draft])
  const pending = chat.filter((m) => m.role === 'approval' && m.status === 'pending').length
  const snap = useStore((s) => s.snap)
  const [view, setView] = useState<'all' | 'talk'>(() => (localStorage.getItem('ss.chatView') as 'all' | 'talk') || 'all')
  const [seenAt, setSeenAt] = useState(0)
  if (!chatOpen && docked) {
    const unseen = chat.filter((m) => (m.role === 'narration' || m.role === 'event' || m.role === 'assistant') && +new Date(m.ts) > seenAt).length
    return (
      <button className="dock-rail" onClick={() => { setSeenAt(Date.now()); setChatOpen(true) }} aria-label="Open SwarmFrame live">
        <span className="live-dot run" />
        <span className="dock-rail-l">Live</span>
        {unseen > 0 && <span className="count">{unseen}</span>}
      </button>
    )
  }
  if (!chatOpen) {
    return (
      <button className="chat-fab" onClick={() => setChatOpen(true)} aria-label="Open the copilot">
        <Icon name="chat" size={20} />
        <span>Ask SwarmFrame</span>
        {pending > 0 && <span className="count">{pending}</span>}
      </button>
    )
  }
  const send = async (t: string) => {
    if (!t.trim()) return
    setText('')
    await post('/api/chat', { text: t, target: st?.target })
  }
  const settings = (body: Record<string, unknown>) => post<ChatState>('/api/chat/settings', body).then((d) => { setSt(d); if (body.reset) setChat(d.messages) })
  const target = st?.target ?? 'copilot'
  const visible = chat.filter((m) => !(m.role === 'system' && !m.text) && (view === 'all' || !['narration', 'event'].includes(m.role)))
  const lr = snap?.live_replay
  const c = snap?.clock
  const state = !c ? '' : c.live ? 'live' : lr ? (lr.on ? 'live replay' : 'catching up') : c.done ? 'replay ended' : c.paused ? 'paused' : 'replaying'
  const mode = snap?.org.llm_label?.short ?? (snap?.org.llm_mode === 'stub' ? 'rules only' : 'Claude')
  const narrate = st?.narrate ? (st.narrate.on ? String(st.narrate.every_s) : 'off') : '60'
  const commentary = st?.commentary ? (st.commentary.on ? String(st.commentary.every_s) : 'off') : '300'
  return (
    <aside className={`chat-dock ${docked ? 'docked' : ''}`} aria-label="SwarmFrame live">
      <div className="chat-head">
        <div className="row" style={{ gap: 8 }}>
          <span className={`live-dot ${state === 'paused' || state === 'replay ended' ? 'off' : 'run'}`} />
          <span className="chat-title">Live</span>
          <span style={{ flex: 1 }} />
          <Menu label="" icon="more" variant="ghost icon-btn" items={[
            { label: 'What to show', head: true },
            { label: 'Everything', icon: view === 'all' ? 'check' : undefined, hint: 'activity lines, findings and conversation', onClick: () => { setView('all'); localStorage.setItem('ss.chatView', 'all') } },
            { label: 'Only the conversation', icon: view === 'talk' ? 'check' : undefined, onClick: () => { setView('talk'); localStorage.setItem('ss.chatView', 'talk') } },
            { sep: true, label: '' },
            ...([['0', 'Activity line every window'], ['60', 'Activity line every minute'], ['300', 'Activity line every 5 minutes'], ['off', 'No activity lines']] as [string, string][]).map(([v, l]) => ({
              label: l, icon: narrate === v ? 'check' : undefined, onClick: () => settings({ narrate: v === 'off' ? { on: false } : { on: true, every_s: +v } }) })),
            ...(snap?.org.llm_mode !== 'stub' ? [{ sep: true, label: '' }, ...([['300', 'Lead summary every 5 minutes'], ['900', 'Lead summary every 15 minutes'], ['off', 'No lead summaries']] as [string, string][]).map(([v, l]) => ({
              label: l, icon: commentary === v ? 'check' : undefined, onClick: () => settings({ commentary: v === 'off' ? { on: false } : { on: true, every_s: +v } }) }))] : []),
            { sep: true, label: '' },
            { label: st?.watch.on ? 'Stop pushing findings to the assistant' : 'Push findings to the assistant', icon: 'eye', hint: 'new findings and revisions go to the agent as they happen', onClick: () => settings({ watch: { on: !st?.watch.on } }) },
            { label: target === 'copilot' ? 'Talk to my own Claude Code session' : 'Talk to the built-in assistant', icon: 'chat', onClick: () => settings({ target: target === 'copilot' ? 'channel' : 'copilot' }) },
            { label: 'New conversation', icon: 'undo', onClick: () => settings({ reset: true }) },
          ]} />
          <button className="btn ghost icon-btn" title={docked ? 'Collapse' : 'Close'} onClick={() => setChatOpen(false)}><Icon name={docked ? 'chevron' : 'x'} size={15} /></button>
        </div>
        <div className="chat-sub">
          <span>{state}{c && !c.live ? ` · ${fmtTime(c.now)}` : ''}</span>{(c?.live || lr?.on) && !c?.paused && <NextUpdate every={c!.window_s} />}<span>·</span><span>{mode}</span>
          {target === 'channel' && <><span>·</span><span>{st?.channel.connected ? 'your Claude Code' : 'no Claude Code session yet'}</span></>}
          {target === 'copilot' && st?.copilot.mode !== 'stub' && st?.copilot.cost_usd ? <><span>·</span><span>${st.copilot.cost_usd.toFixed(2)}</span></> : null}
        </div>
        {target === 'channel' && !st?.channel.connected && (
          <div className="card" style={{ marginTop: 8, fontSize: 12.5 }}>
            Start Claude Code in the SwarmFrame folder with the SwarmFrame channel; it reads <span className="mono">.mcp.json</span> and connects back here.
            <div className="untrusted" style={{ marginTop: 6, color: 'var(--ink)' }}>{st?.channel.command}</div>
          </div>
        )}
      </div>

      <div className="chat-body">
        {!visible.length && (
          <div style={{ padding: '18px 4px' }}>
            <div style={{ fontSize: 14, color: 'var(--ink-2)', marginBottom: 10, lineHeight: 1.5 }}>
              A line about each stretch of activity appears here, every finding the moment it is raised, and answers to your questions.</div>
            <div className="stack" style={{ gap: 6 }}>
              {SUGGEST.map((s) => <button key={s} className="btn sm" style={{ justifyContent: 'flex-start', whiteSpace: 'normal', textAlign: 'left' }} onClick={() => send(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {visible.map((m) => <Msg key={m.id} m={m} />)}
        {typing && <div className="msg assistant"><span className="typing"><i /><i /><i /></span></div>}
        <div ref={end} />
      </div>

      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(text) }}>
        <textarea className="input" rows={2} value={text} placeholder={target === 'copilot' ? 'Ask, or tell it to act…' : 'Message your Claude Code session…'}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(text) } }} />
        <button className="btn primary" type="submit" disabled={!text.trim()}><Icon name="arrow" size={15} /></button>
      </form>
    </aside>
  )
}

/** "next update in 23 s": the stream is continuous, so say when the next window lands */
function NextUpdate({ every }: { every: number }) {
  const tick = useStore((s) => s.tick)
  const [at, setAt] = useState(Date.now())
  const [, force] = useState(0)
  useEffect(() => { setAt(Date.now()) }, [tick])
  useEffect(() => { const t = setInterval(() => force((x) => x + 1), 1000); return () => clearInterval(t) }, [])
  const left = Math.max(0, Math.round(every - (Date.now() - at) / 1000))
  return <span>· next update in {left} s</span>
}

function Msg({ m }: { m: ChatMsg }) {
  const who = m.via === 'channel' ? 'your Claude Code' : 'copilot'
  if (m.role === 'narration') return (
    <div className={`msg narration ${m.meta?.quiet ? 'quiet' : ''} ${m.meta?.trend ? 'trend-' + m.meta.trend.replace(' ', '-') : ''}`}>
      <span className="mono when">{fmtTime(m.meta?.to ?? m.stream_ts)}</span><span className="n-text">{m.text}<CiteMarks cites={m.meta?.cites} max={3} /></span>
    </div>
  )
  if (m.role === 'viewer') return <div className="msg viewer"><div className="bubble">{m.text}</div><div className="mono muted when">{fmtTime(m.ts)} · to {who}</div></div>
  if (m.role === 'assistant' && m.meta?.orientation) {
    const o = m.meta.orientation
    return (
      <div className="msg assistant orientation">
        <div className="label" style={{ marginBottom: 3 }}>{who} · here is what I set up</div>
        <div className="answer">
          <b>{o.source}{o.synthetic ? ' (synthetic)' : ''}</b>: {o.how}.{' '}
          {o.pages.length > 0 && <>I built {o.pages.map((p: any) => p.title).join(', ')} beside the Brief. </>}
          The {o.team.title} team reads it, with {o.reader}. I will post a line here every window and flag findings, with sources, as they appear.
        </div>
        <details className="answer-sources" open>
          <summary className="mono">how to study it</summary>
          <StudyGuide o={o} compact />
        </details>
      </div>
    )
  }
  if (m.role === 'assistant') return (
    <div className="msg assistant">
      <div className="label" style={{ marginBottom: 3 }}>{who}</div>
      <div className="answer"><Rich text={m.text} cites={m.meta?.cites} /></div>
      {m.meta?.cites?.length > 0 && (
        <details className="answer-sources">
          <summary className="mono">sources · {m.meta.cites.length}</summary>
          <SourceList cites={m.meta.cites} />
        </details>
      )}
      {m.meta?.uncited && <div className="mono muted uncited" title="The answer names no claim the dashboard can open. Read it as interpretation, or ask for the evidence.">no sources cited · interpretation</div>}
    </div>
  )
  if (m.role === 'tool') return <div className="msg tool"><span className="mono"><Icon name="spark" size={11} /> {m.text}</span></div>
  if (m.role === 'event') {
    const items: { ts: string; kind: string; level: string; text: string; cites?: Cite[]; explain?: { what: string; why: string; benign: string } }[] = m.meta?.events ?? []
    const LV: Record<string, string> = { PAGE: 'act', ALERT: 'act', INVESTIGATE: 'look', WATCH: 'watch' }
    return (
      <div className="msg event">
        {(items.length ? items : [{ ts: m.stream_ts ?? '', kind: 'NEW', level: '', text: m.text }]).slice(0, 3).map((x, i) => (
          <div key={i} className="ev-item">
            <div className="label" style={{ color: 'var(--accent)' }}>{x.kind === 'REVISED' ? 'revised' : 'new finding'} · {fmtTime(x.ts)}{x.level && <span className={`ev-lv lv-${LV[x.level] ?? 'watch'}`}>{x.level.toLowerCase()}</span>}</div>
            <div className="ev-text">{x.explain?.what || x.text} <CiteMarks cites={x.cites} max={4} /></div>
            {x.explain?.why && <details className="ev-why"><summary>Why it may matter</summary>{x.explain.why} <span className="muted">Innocent reading: {x.explain.benign}</span></details>}
          </div>
        ))}
        {items.length > 3 && <div className="mono muted" style={{ fontSize: 11, marginTop: 6 }}>and {items.length - 3} more · see Attention</div>}
      </div>
    )
  }
  if (m.role === 'approval') return (
    <div className="msg approval" style={{ borderColor: m.status === 'pending' ? 'var(--lv-alert)' : 'var(--line)' }}>
      <div className="label" style={{ color: m.status === 'pending' ? 'var(--lv-alert)' : 'var(--ink-3)' }}>
        {m.meta?.kind === 'permission' ? 'permission request' : 'needs your approval'} · {who}</div>
      <div style={{ fontSize: 13.5, margin: '3px 0' }}>{m.text}</div>
      {m.meta?.input_preview && <div className="untrusted" style={{ maxHeight: 120 }}>{m.meta.input_preview}</div>}
      {m.status === 'pending' ? (
        <div className="row" style={{ gap: 6, marginTop: 6 }}>
          <button className="btn sm primary" onClick={() => post('/api/chat/approval', { id: m.id, approve: true })}>Approve</button>
          <button className="btn sm" onClick={() => post('/api/chat/approval', { id: m.id, approve: false })}>Deny</button>
        </div>
      ) : <div className="mono muted">{m.status}</div>}
    </div>
  )
  return <div className="msg system mono muted">{m.text}</div>
}
