import React, { useEffect, useMemo, useRef, useState } from 'react'
import { DEMO_FIELD, SwarmField } from '../components/SwarmField'
import { estimate, fmtRate } from '../components/speed'
import { api, get, post } from '../api'
import { useStore } from '../store'
import type { SourceInfo } from '../types'
import { Icon, Logo } from '../components/ui'
import { ProfileView } from './Views'
import { startReplay } from './Brief'
import { CadencePicker, prettyModel, DEFAULT_CADENCE, DEFAULT_READING, ReaderPicker, readingOverrides, TEAM_PLAIN, type Cadence, type Reading } from '../components/ReadingSetup'

export const MODES = [
  { v: 'stub', title: 'Rules only', cost: 'free', short: 'Rules only',
    body: 'Deterministic watchers, analysts and composer. No model calls; nothing leaves this machine. Findings come from fixed rules, so nothing is "understood".' },
  { v: 'cheap', title: 'Claude, economical', cost: 'small cost', short: 'Claude · Sonnet 5.5 low',
    body: 'Analysts, investigations, the copilot and the dashboard and World designers are Claude Code sessions on Sonnet 5.5 at low effort, through your Claude Code login.' },
  { v: 'full', title: 'Claude, full', cost: 'higher cost', short: 'Claude · full',
    body: 'The same, with each role on the model and effort set in the organization config. Best reading, highest cost.' },
] as const

type Choice = 'claude_code' | 'stream' | 'village' | 'village_synthetic' | 'scale' | 'transluce' | 'german'
const CHOICE_NAME: Record<string, string> = {
  claude_code: 'your Claude Code swarm', stream: 'your event stream', village: 'the AI Village slice', village_synthetic: 'the planted village',
  scale: 'the planted swarm', transluce: 'the Transluce catalog', german: 'the German message board',
}
type TeamLib = { topologies: { id: string; title: string; description: string; roles: number }[]; pack_defaults: Record<string, { topology: string; preset?: string | null; reason: string }> }
interface Info { root: string; hook_script: string; python: string; url: string }
interface Slice { goal: string; start: string; days: number; chat: number; sessions: number; agents: number; title: string }

const LIVE_MIN_EVENTS = 150

/** The whole user journey, said once at the top of compose mode. */
const JOURNEY = [
  { t: 'You pick the data', b: 'A live stream, or one of the recorded swarms below.' },
  { t: 'An agent reads it', b: 'It works out what the data records (who, when, messages, shared things) and what it cannot show.' },
  { t: 'It builds your dashboard', b: 'It sets up the pages and a team of analysts for this data, and explains why it chose each one.' },
  { t: 'You watch, it reports', b: 'A live column gives an update every window and raises findings with numbered sources you can open. Ask it anything.' },
]

/** Remember, per browser tab, which session has been composed, so reloading lands on the dashboard. */
export const composedKey = 'ss.composed'
export function markComposed(sessionId: string | undefined) {
  try { if (sessionId) sessionStorage.setItem(composedKey, sessionId) } catch { /* ignore */ }
  useStore.setState({ composed: sessionId ?? null })
}
export function wasComposed(sessionId: string | undefined): boolean {
  try { return !!sessionId && sessionStorage.getItem(composedKey) === sessionId } catch { return false }
}

export function Compose() {
  const snap = useStore((s) => s.snap)
  const setRoute = useStore((s) => s.setRoute)
  const [stage, setStage] = useState<'choose' | 'compose'>(() => 'choose')
  const [sources, setSources] = useState<SourceInfo[]>([])
  const [orgs, setOrgs] = useState<{ id: string; name: string }[]>([])
  const [slices, setSlices] = useState<Slice[]>([])
  const [info, setInfo] = useState<Info | null>(null)
  const [choice, setChoice] = useState<Choice>('village')
  const [demo, setDemo] = useState(false)
  const [goal, setGoal] = useState('680a1b42')
  const [agents, setAgents] = useState(2000)
  const [org, setOrg] = useState('default')
  const [reading, setReading] = useState<Reading>(DEFAULT_READING)
  const [cadence, setCadence] = useState<Cadence>(DEFAULT_CADENCE)
  const [morePresets, setMorePresets] = useState(false)
  const llm = reading.provider === 'none' ? 'stub' : 'custom'
  const [team, setTeam] = useState<string>('auto')
  const [teams, setTeams] = useState<TeamLib | null>(null)
  const [focus, setFocus] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const [speed, setSpeed] = useState<number | 'max' | null>(null)     // null: the source's recommended speed
  const [feedSpeed, setFeedSpeed] = useState(240)
  const [simRate, setSimRate] = useState(3)
  const [play, setPlay] = useState<'live' | 'replay'>('live')    // replays with a live stretch default to watching it live
  const [gwFull, setGwFull] = useState(false)     // German board: the June surge (default) or the whole record

  useEffect(() => {
    get('/api/sources').then(setSources).catch(() => {})
    get('/api/orgs').then(setOrgs).catch(() => {})
    get('/api/sources/ai_village/slices').then(setSlices).catch(() => {})
    get('/api/compose/info').then(setInfo).catch(() => {})
    get('/api/agents/topologies').then(setTeams).catch(() => {})
  }, [])
  const has = (id: string) => sources.find((s) => s.id === id)?.has_data
  const SRC: Record<string, string> = { village: 'ai_village', village_synthetic: 'ai_village', scale: 'swarm_scale', transluce: 'transluce', german: 'german_wiki', claude_code: 'claude_code', stream: 'generic_stream' }
  const packDefault = teams?.pack_defaults?.[SRC[choice]]
  const presetId = packDefault?.preset && packDefault.preset !== 'auto' ? packDefault.preset : null
  const teamTitle = (id: string) => teams?.topologies.find((t) => t.id === id)?.title ?? id
  const autoLabel = teamTitle(packDefault?.topology ?? 'lead')
  const replaySrc = sources.find((s) => s.id === SRC[choice])
  const replayHours = choice === 'village_synthetic' ? replaySrc?.replay_hours_synthetic ?? replaySrc?.replay_hours : choice === 'scale' ? (replaySrc?.replay_hours ?? 36) : choice === 'german' && gwFull ? replaySrc?.replay_hours_full ?? replaySrc?.replay_hours : replaySrc?.replay_hours
  const speeds = replaySrc?.speeds ?? []
  // the live stretch is a real moment: not in the synthetic village, and only in the village's default goal period
  const liveOk = !!replaySrc?.live_stretch && choice !== 'village_synthetic' && !(choice === 'village' && goal !== '680a1b42')
  const recommended = (replaySrc?.autoplay ?? null) as number | 'max' | null
  const chosen = speed ?? recommended
  useEffect(() => { setSpeed(null) }, [choice])
  useEffect(() => { if (replaySrc) setPlay(replaySrc.play_default === 'replay' ? 'replay' : 'live') }, [choice, replaySrc?.id])
  const running = snap && !snap.empty ? snap : null

  const start = async () => {
    setBusy(true); setErr('')
    const liveNow = liveOk && play === 'live'
    const p: Record<string, any> = { org, overrides: { ...readingOverrides(reading), ...(team !== 'auto' ? { 'agents.topology': team } : {}) }, ...(speed != null && replaySrc && !liveNow ? { speed } : {}),
      ...(liveNow ? { live: true, autoplay: true } : {}) }
    if (choice === 'claude_code') Object.assign(p, { source: 'claude_code', simulate: demo ? 200 : 0, sim_rate: simRate })
    else if (choice === 'stream') Object.assign(p, { source: 'generic_stream', demo_feed: demo ? { agents: 400, hours: 10, speed: feedSpeed } : undefined })
    else if (choice === 'village') Object.assign(p, { source: 'ai_village', goal })
    else if (choice === 'village_synthetic') Object.assign(p, { source: 'ai_village', path: 'synthetic' })
    else if (choice === 'scale') Object.assign(p, { source: 'swarm_scale', slice: { agents, hours: 36 } })
    else if (choice === 'german') Object.assign(p, { source: 'german_wiki', ...(gwFull ? { slice: { full: true } } : {}) })
    else Object.assign(p, { source: 'transluce' })
    try {
      await api.session(p)
      // how often the live column speaks
      await post('/api/chat/settings', { narrate: { every_s: cadence.narrate }, commentary: { on: cadence.commentary > 0, every_s: cadence.commentary } }).catch(() => {})
      document.querySelector('.content')?.scrollTo({ top: 0 })
      setStage('compose')
    } catch (e: any) { setErr(String(e.message || e)) } finally { setBusy(false) }
  }
  const open = (r: NonNullable<typeof running>) => {
    markComposed(r.session_id)
    setRoute('brief')
    if (!r.clock.live && r.clock.paused && r.autoplay) startReplay(r)
  }

  if (stage === 'compose' && running) return <Composing focus={focus} onDone={() => open(running)} onBack={() => setStage('choose')} />

  const card = ({ id, meta, title, body, children }: { id: Choice; meta: string; title: string; body: string; children?: React.ReactNode }) => (
    <div key={id} className={`source-card ${choice === id ? 'on' : ''}`} onClick={() => setChoice(id)} role="radio" aria-checked={choice === id} tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setChoice(id) }}>
      <div className="row" style={{ justifyContent: 'space-between' }}><span className="label">{meta}</span>
        <span className={`radio ${choice === id ? 'on' : ''}`} aria-hidden /></div>
      <div className="display" style={{ fontSize: 21, lineHeight: 1.15, marginTop: 4 }}>{title}</div>
      <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>{body}</div>
      {choice === id && children && <div style={{ marginTop: 12 }} onClick={(e) => e.stopPropagation()}>{children}</div>}
    </div>
  )

  const hookCmd = info ? `${info.python} ${info.hook_script}` : 'python scripts/swarmscope_hook.py'
  return (
    <div className="fade-in" style={{ maxWidth: 1180, margin: '0 auto', padding: '4vh 4px 40px' }}>
      <section className="compose-hero">
        <SwarmField input={DEMO_FIELD} />
        <div className="row" style={{ gap: 12, marginBottom: 10 }}><span className="logo-accent"><Logo size={30} /></span><span className="label">Compose mode</span></div>
        <h1 className="compose-title">What should we watch?</h1>
        <p className="compose-lede">
          Pick a source and press Start. From there an agent does the work: it reads the data, builds a dashboard for it,
          picks a team of analysts, and keeps telling you what is happening.</p>
        <ol className="journey" aria-label="How SwarmFrame works">
          {JOURNEY.map((j, i) => (
            <li key={j.t} className={i === 0 ? 'now' : ''}>
              <span className="j-n">{i + 1}</span>
              <span className="j-t">{j.t}</span>
              <span className="j-b">{j.b}</span>
            </li>
          ))}
        </ol>
      </section>

      {running && (
        <div className="card row" style={{ margin: '16px 0', padding: '12px 16px', gap: 14 }}>
          <span className="live-dot run" />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600 }}>A session is running: {running.source.title}</div>
            <div className="mono muted">{running.lens ?? 'Default'} lens · models {running.org.llm_mode === 'stub' ? 'off' : running.org.llm_mode}</div>
          </div>
          <button className="btn" onClick={() => setStage('compose')}>Compose it again</button>
          <button className="btn primary" onClick={() => open(running)}>Open the dashboard <Icon name="arrow" size={14} /></button>
        </div>
      )}

      <div className="two-col" style={{ gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)' }}>
        <div className="stack">
          <div className="label"><span className="step-n">1</span>Pick the data · link your own stream</div>
          {card({ id: "stream", meta: "Any source · live", title: "Any event stream (JSON)", body: "Post events from any swarm. Nothing is declared up front: capabilities are inferred from what arrives, and the dashboard is composed around them.", children: <>
            <div className="mono" style={{ fontSize: 11, lineHeight: 1.5 }}>
              <div className="muted">POST a JSON list to {info?.url ?? 'http://127.0.0.1:8765'}/ingest/events. Only <b>action</b> is required; every other field adds what the dashboard can show.</div>
              <pre style={{ margin: '4px 0', whiteSpace: 'pre-wrap', background: 'var(--sunken)', padding: 8, borderRadius: 8 }}>{`[{"ts": "2026-10-03T14:05:00Z", "actor": "agent-17",
  "group": "team-a", "action": "tool.write",
  "object": "repo/README.md", "family": "files",
  "text": "optional agent-written text",
  "attrs": {"model": "sonnet"}}]`}</pre>
            </div>
            <label className="row mono" style={{ marginTop: 6, gap: 6 }}><input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} />{demo ? 'on: ' : 'off: '}play a sample swarm into it (400 agents, 240× real time)</label>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>After Connect, SwarmFrame waits for about {LIVE_MIN_EVENTS} events, works out what your stream contains, and composes a Brief and a few pages.</div>
          </> })}
        </div>
        <div className="stack">
          <div className="label"><span className="step-n" style={{ visibility: 'hidden' }}>1</span>or explore recorded swarm data</div>
          {card({ id: "village", meta: !sources.length ? 'AI Village' : has('ai_village') ? 'AI Village · real subset' : 'AI Village · not downloaded', title: "AI Village", body: "Twenty-one AI agents with their own computers and a shared chat, working toward a common goal for a week: every message, computer session and goal, plus what they did between messages (memory checkpoints, pauses, searches, outreach requests and the reasoning behind each action).", children: <>
            <select className="input" value={goal} onChange={(e) => setGoal(e.target.value)}>
              {[...slices].sort((a, b) => (b.goal.startsWith('680a1b42') ? 1 : 0) - (a.goal.startsWith('680a1b42') ? 1 : 0)).map((s) => <option key={s.goal} value={s.goal.slice(0, 8)}>{s.goal.startsWith('680a1b42') ? 'Recommended · ' : ''}{s.start.slice(0, 10)} · {s.days} days · {s.agents} agents · {s.chat} messages</option>)}
              {!slices.length && <option value="680a1b42">default slice</option>}
            </select>
          </> })}
          {card({ id: "transluce", meta: !sources.length ? 'Transluce' : has('transluce') ? 'Transluce · real catalog' : 'Transluce · synthetic stand-in', title: "Agent activity on the web", body: "A historical catalog, not a live swarm: 37,649 web-scan reports that Transluce attributes to autonomous agents (Oct 2023 to Sep 2026). Each names the data source targeted, how it was reached and how confident the attribution is. No agent identities." })}
          {card({ id: "german", meta: has('german_wiki') ? 'German message board · real export' : 'German message board · synthetic stand-in', title: "The German message board", body: "Handles writing on a shared wiki (May to July 2026): separate groups converge on question pages, text spreads between them, and moderators delete pages in sweeps. Handles are names, not confirmed agents.", children: <>
            <div className="seg sm" style={{ marginTop: 8 }} onClick={(e) => e.stopPropagation()}>
              <button className={!gwFull ? 'on' : ''} onClick={() => { setChoice('german'); setGwFull(false) }}>The June surge · Jun 10–25</button>
              <button className={gwFull ? 'on' : ''} onClick={() => { setChoice('german'); setGwFull(true) }}>Whole record · May 17–Jul 14</button>
            </div>
          </> })}
        </div>
      </div>

      <div className="compose-foot">
        <div className="label" style={{ marginBottom: 8 }}><span className="step-n">2</span>Who does the reading? <span className="muted" style={{ textTransform: 'none', letterSpacing: 0 }}>· the analysts, the composer and the assistant in the live column</span></div>
        <ReaderPicker value={reading} onChange={setReading} />
        <div style={{ marginTop: 16 }}>
          <div className="label" style={{ marginBottom: 8 }}><span className="step-n">3</span>How is the analyst team organised?</div>
          <div className="team-pick" role="radiogroup" aria-label="Team">
            <button role="radio" aria-checked={team === 'auto'} className={`team-opt ${team === 'auto' ? 'on' : ''}`} onClick={() => setTeam('auto')}>
              <span className="team-top"><span className="mode-dot" />{autoLabel}<span className="mode-cost">default</span></span>
              <span className="mode-body">{TEAM_PLAIN[packDefault?.topology ?? 'lead'] ?? TEAM_PLAIN.lead}</span>
            </button>
            {presetId && (
              <button role="radio" aria-checked={team === presetId} className={`team-opt ${team === presetId ? 'on' : ''}`} onClick={() => setTeam(presetId)}>
                <span className="team-top"><span className="mode-dot" />{teamTitle(presetId)}<span className="mode-cost">suits this source</span></span>
                <span className="mode-body">{TEAM_PLAIN[presetId] ?? ''}{packDefault?.reason ? ` Suggested here because ${packDefault.reason}.` : ''}</span>
              </button>
            )}
            {morePresets && (teams?.topologies ?? []).filter((t) => t.id !== 'lead' && t.id !== presetId && t.id !== (packDefault?.topology ?? 'lead')).map((t) => (
              <button key={t.id} role="radio" aria-checked={team === t.id} className={`team-opt ${team === t.id ? 'on' : ''}`} onClick={() => setTeam(t.id)} title={t.description}>
                <span className="team-top"><span className="mode-dot" />{t.title}<span className="mode-cost">preset</span></span>
                <span className="mode-body">{TEAM_PLAIN[t.id] ?? t.description}</span>
              </button>
            ))}
          </div>
          <button className="link" style={{ marginTop: 8 }} onClick={() => setMorePresets(!morePresets)}>{morePresets ? 'Hide the other presets' : 'Show the other team presets'}</button>
        </div>
        {liveOk && replaySrc?.live_stretch && (
          <div style={{ marginTop: 16 }}>
            <div className="label" style={{ marginBottom: 8 }}><span className="step-n">4</span>How to play it</div>
            <div className="mode-pick two">
              <button className={`mode-opt ${play === 'live' ? 'on' : ''}`} onClick={() => setPlay('live')}>
                <span className="mode-top"><span className="mode-dot" />Watch live<span className="mode-cost">real time</span></span>
                <span className="mode-body">{replaySrc.live_stretch.label ? `${replaySrc.live_stretch.label[0].toUpperCase()}${replaySrc.live_stretch.label.slice(1)}` : 'The busiest real stretch'}, as it happened ({replaySrc.live_stretch.rate}). The dashboard refreshes every {replaySrc.live_stretch.window_seconds ?? 30} seconds, after a short catch-up so the monitors know what usual looks like.</span>
              </button>
              <button className={`mode-opt ${play === 'replay' ? 'on' : ''}`} onClick={() => setPlay('replay')}>
                <span className="mode-top"><span className="mode-dot" />Replay the record<span className="mode-cost">faster</span></span>
                <span className="mode-body">The whole period, sped up, to see how it unfolded from start to end.</span>
              </button>
            </div>
          </div>
        )}
        {replaySrc && speeds.length > 0 && !(liveOk && play === 'live') && (
          <div style={{ marginTop: 16 }}>
            <div className="label" style={{ marginBottom: 8 }}>Replay speed <span className="muted" style={{ textTransform: 'none', letterSpacing: 0 }}>· you can change it any time from the top bar</span></div>
            <div className="speed-pick">
              {[...speeds, { v: 1, label: 'Real time', note: 'the recorded pace; only for watching a short stretch' }].map((o) => (
                <button key={String(o.v)} className={`speed-opt ${chosen === o.v ? 'on' : ''}`} onClick={() => setSpeed(o.v as number | 'max')} title={o.note}>
                  <span className="speed-l">{o.label}{o.v === recommended && <span className="speed-rec">recommended</span>}</span>
                  <span className="speed-r">{fmtRate(o.v as number | 'max')}</span>
                  <span className="speed-e">{estimate(replayHours, o.v as number | 'max')}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {choice === 'stream' && demo && (
          <div style={{ marginTop: 16 }}>
            <div className="label" style={{ marginBottom: 8 }}>Sample feed speed</div>
            <div className="seg">{[[1, 'Real time'], [60, '1 min / s'], [240, '4 min / s'], [960, '16 min / s']].map(([v, l]) => <button key={v} className={feedSpeed === v ? 'on' : ''} onClick={() => setFeedSpeed(v as number)}>{l}</button>)}</div>
          </div>
        )}
        {choice === 'claude_code' && demo && (
          <div style={{ marginTop: 16 }}>
            <div className="label" style={{ marginBottom: 8 }}>Simulated swarm activity <span className="muted" style={{ textTransform: 'none', letterSpacing: 0 }}>· live, so always real time</span></div>
            <div className="seg">{[[1, 'Quiet'], [3, 'Normal'], [8, 'Busy']].map(([v, l]) => <button key={v} className={simRate === v ? 'on' : ''} onClick={() => setSimRate(v as number)}>{l}</button>)}</div>
          </div>
        )}
        <div style={{ marginTop: 16 }}>
          <div className="label" style={{ marginBottom: 8 }}><span className="step-n">5</span>How often should it report? <span className="muted" style={{ textTransform: 'none', letterSpacing: 0 }}>· new findings always appear at once; change this later from the live column</span></div>
          <CadencePicker value={cadence} onChange={setCadence} models={reading.provider !== 'none'} />
        </div>
        <div className="row" style={{ gap: 18, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 16 }}>
          <div style={{ flex: 1, minWidth: 280 }}>
            <div className="label" style={{ marginBottom: 4 }}>Anything to focus on? (optional)</div>
            <input className="input" style={{ width: '100%' }} value={focus} onChange={(e) => setFocus(e.target.value)}
              placeholder="e.g. which teams converge on shared files; how evidence grades shift by target" />
          </div>
          <button className="btn accent lg" disabled={busy} onClick={start}>
            {busy ? 'Connecting…' : 'Start: read it and build my dashboard'} <Icon name="arrow" size={15} />
          </button>
        </div>
        <div className="will-do">
          <span className="label">When you press Start</span>
          <span>An agent reads <b>{CHOICE_NAME[choice]}</b>{choice === 'claude_code' || choice === 'stream' ? ' as events arrive' : ''}, builds a dashboard and picks
            {team === 'auto' ? <> the <b>{autoLabel}</b> team</> : <> the <b>{teamTitle(team)}</b> team</>},
            {' '}with {reading.provider === 'none' ? <><b>fixed rules</b> doing the reading</> : <><b>{prettyModel(reading.primary.model)}</b> as the lead and <b>{prettyModel(reading.subagents.model)}</b> for explorers</>}. {liveOk && play === 'live' && replaySrc?.live_stretch
              ? <>Then it plays <b>{replaySrc.live_stretch.label ?? 'the busiest stretch'}</b> in real time</> : choice === 'claude_code' || choice === 'stream' ? <>Then it watches live</> : <>Then it replays the record</>}
            {' '}and explains what it built in the live column on the right, posting updates as the data comes in.</span>
        </div>
        <button className="disclosure" onClick={() => setAdvanced(!advanced)} aria-expanded={advanced}>
          <span className={`chev-sm ${advanced ? 'open' : ''}`}><Icon name="chevron" size={13} /></span>
          Advanced: how SwarmFrame's analysts are organised <span className="muted">· {orgs.find((o) => o.id === org)?.name ?? org}</span>
        </button>
        {advanced && (
          <div className="advanced">
            <div>
              <div className="label" style={{ marginBottom: 4 }}>Monitoring organization</div>
              <select className="input" value={org} onChange={(e) => setOrg(e.target.value)} style={{ minWidth: 240 }}>
                {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
              <div className="muted adv-note">How SwarmFrame's own analysts are arranged. The default (an adaptive hierarchy that triages the swarm) is what the rest of the dashboard assumes; the others are baselines for comparison.</div>
            </div>
          </div>
        )}
        {err && <div className="mono" style={{ color: 'var(--st-contradicted)', marginTop: 8 }}>{err}</div>}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ the orientation: how to study this source */
export interface Orientation {
  source: string; description: string; how: string; have: string[]; lack: string[]; synthetic: boolean
  pages: { title: string; why: string }[]; team: { title: string; roles: string[]; why: string }; reader: string
  questions: string[]; first: string[]; naming?: string
}

/** What to do first and what to ask, for this source. Questions drop into the live column's question box. */
export function StudyGuide({ o, compact = false }: { o: Orientation; compact?: boolean }) {
  const ask = (q: string) => { useStore.getState().setChatOpen(true); useStore.setState({ chatDraft: q }) }
  return (
    <div className={`study ${compact ? 'compact' : ''}`}>
      {!compact && <div className="study-what">
        <b>What this data can show.</b> {o.have.length ? `It records ${o.have.join(', ')}.` : ''}
        {o.lack.length ? <span className="muted"> Not available here: {o.lack.join(', ')}.</span> : null}
      </div>}
      {o.naming && <div className="study-what"><b>About the names.</b> {o.naming}</div>}
      {!compact && <div className="study-what"><b>Who is reading it.</b> The {o.team.title} team ({o.team.roles.join(', ')}){o.team.why ? `, because ${o.team.why}` : ''}. Reading: {o.reader}.</div>}
      {!compact && <div className="study-h">How to study it</div>}
      <ol className="study-steps">{o.first.map((f) => <li key={f}>{f}</li>)}</ol>
      {o.questions.length > 0 && <>
        <div className="study-h">Good first questions</div>
        <div className="study-qs">{o.questions.map((q) => <button key={q} className="btn sm" onClick={() => ask(q)} title="Put this in the live column's question box">{q}</button>)}</div>
      </>}
    </div>
  )
}

/* ------------------------------------------------------------------ the composing stage */
function Composing({ focus, onDone, onBack }: { focus: string; onDone: () => void; onBack: () => void }) {
  const snap = useStore((s) => s.snap)!
  const dash = useStore((s) => s.dash)
  const designing = useStore((s) => s.designing)
  const chat = useStore((s) => s.chat)
  const [prof, setProf] = useState<any>(null)
  const [phase, setPhase] = useState<'waiting' | 'composing' | 'world' | 'done'>('waiting')
  const started = useRef(false)
  const t0 = useRef(Date.now())
  const live = snap.source.live
  const received = snap.stream?.received ?? snap.population.total_events_seen
  const ready = !live || received >= LIVE_MIN_EVENTS || (Date.now() - t0.current > 25000 && received >= 30)

  useEffect(() => { get('/api/dashboard/profile').then(setProf).catch(() => {}) }, [snap.clock.index, phase])
  // a source composed before keeps its views (data/composed.json); Recompose asks the designers again
  const [reused, setReused] = useState<{ at: string; mode?: string } | null>(null)
  const [force, setForce] = useState(0)
  useEffect(() => {
    if (started.current || !ready) return
    started.current = true
    setPhase('composing')
    post<any>('/api/dashboard/design', { instruction: focus, force: force > 0 }).then((r) => setReused(r?.reused ?? null)).catch(() => setPhase('done'))
  }, [ready, focus, force])
  const recompose = () => { started.current = false; setReused(null); setWorld(null); setPhase('waiting'); setForce((x) => x + 1) }
  useEffect(() => { if (phase === 'composing' && started.current && !designing) { const t = setTimeout(() => setPhase('world'), 600); return () => clearTimeout(t) } }, [designing, phase])
  // step 5: lay out the World (the preset, or composed from what this stream can show)
  const [world, setWorld] = useState<any>(null)
  useEffect(() => {
    if (phase !== 'world') return
    let live = true
    post('/api/world/design', { force: force > 0 }).catch(() => {}).finally(() => {
      setTimeout(() => get('/api/world/spec').then((d) => { if (live) { setWorld(d.spec); setPhase('done') } }).catch(() => live && setPhase('done')), 700)
    })
    return () => { live = false }
  }, [phase])

  const [orient, setOrient] = useState<Orientation | null>(null)
  useEffect(() => { if (phase === 'done') get<Orientation>('/api/orientation').then(setOrient).catch(() => {}) }, [phase])
  const pages = dash?.spec.pages ?? []
  const builtIn = pages.filter((p) => p.by === 'pack' && p.id !== 'brief')
  const brief = pages.find((p) => p.id === 'brief')
  const activity = pages.filter((p) => p.id !== 'brief')
  const play = snap.live_replay ? `with a short catch-up, then ${snap.live_replay.label} in real time` : snap.autoplay === 'max' ? 'loading the whole history as fast as possible' : typeof snap.autoplay === 'number' ? `playing at ${snap.autoplay >= 3600 ? `${snap.autoplay / 3600} simulated hour${snap.autoplay > 3600 ? 's' : ''}` : `${snap.autoplay / 60} simulated minutes`} per second` : ''
  const log = useMemo(() => chat.filter((m) => m.meta?.designer || /Dashboard designer|Dashboard redesigned/.test(m.text)).slice(-4), [chat])
  const Step = ({ n, title, state, children }: { n: number; title: string; state: 'done' | 'active' | 'todo'; children?: React.ReactNode }) => (
    <div className="row" style={{ alignItems: 'flex-start', gap: 12, padding: '12px 0', borderTop: n > 1 ? '1px solid var(--line-2)' : undefined }}>
      <span className="mono" style={{ width: 24, height: 24, borderRadius: 12, display: 'grid', placeItems: 'center', flex: 'none',
        background: state === 'done' ? 'var(--st-observed)' : state === 'active' ? 'var(--accent)' : 'var(--sunken)', color: state === 'todo' ? 'var(--ink-3)' : '#fff' }}>
        {state === 'done' ? '✓' : n}</span>
      <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 600 }}>{title}</div><div style={{ marginTop: 4 }}>{children}</div></div>
    </div>
  )
  return (
    <div className="fade-in" style={{ maxWidth: 1180, margin: '0 auto', padding: '4vh 4px 40px' }}>
      <div className="row" style={{ gap: 12, marginBottom: 6 }}><Logo size={30} /><span className="label">Compose mode · {snap.source.title}</span></div>
      <div className="display" style={{ fontSize: 40, lineHeight: 1.1 }}>{phase === 'done' ? 'Your dashboard is ready.' : phase === 'world' ? 'Laying out the World…' : 'Composing a dashboard around this stream…'}</div>
      <div className="two-col" style={{ gridTemplateColumns: 'minmax(0, 6fr) minmax(0, 5fr)' }}>
        <div className="card" style={{ padding: '6px 18px' }}>
          <Step n={1} title="Source connected" state="done">
            <span className="muted">{snap.source.title}{live ? ' · live' : ' · replay'}{snap.source.synthetic ? ' · synthetic' : ''}</span>
          </Step>
          <Step n={2} title="Reading the stream’s structure" state={ready ? 'done' : 'active'}>
            {live && !ready
              ? <span className="stack" style={{ gap: 6 }}>
                  <span className="mono">waiting for events: {received} received (composing at {LIVE_MIN_EVENTS})</span>
                  {received === 0 && !snap.stream?.feed && <span className="muted" style={{ fontSize: 13 }}>Nothing yet. Post events to <span className="mono">/ingest/events</span> from your swarm, or{' '}
                    <button className="link" onClick={() => post('/api/stream/demo')}>play the sample swarm</button>.</span>}
                </span>
              : <span className="muted">{live
                ? `${received.toLocaleString()} events · capabilities inferred from what arrived`
                : `${(prof?.events?.total ?? 0).toLocaleString()} events in the recording · capabilities declared by the source pack`}</span>}
          </Step>
          <Step n={3} title="The source's default views" state={ready ? 'done' : 'todo'}>
            {builtIn.length || brief?.panels.length
              ? <span className="muted">{builtIn.length ? builtIn.map((p) => p.title).join(' · ') : 'a Brief'}: a starting point you can change or reset at any time</span>
              : <span className="muted">none for this source; the composer builds it</span>}
          </Step>
          <Step n={4} title={reused ? 'Using the views saved for this source' : snap.org.llm_mode === 'stub' ? 'Composing (free composer)' : 'Composing with Claude (dashboard-designer skill)'} state={phase === 'done' || phase === 'world' ? 'done' : phase === 'composing' ? 'active' : 'todo'}>
            {reused && <div className="reused-note">Composed on {new Date(reused.at).toLocaleDateString([], { month: 'short', day: 'numeric' })}{reused.mode && reused.mode !== 'stub' ? ' with Claude' : ''}; nothing was recomputed. <button className="link" onClick={recompose}>Recompose</button></div>}
            {phase === 'composing' && <span className="mono" style={{ color: 'var(--accent)' }}>{designing ? 'designing…' : 'finishing…'}</span>}
            {phase !== 'done' && log.map((m) => <div key={m.id} style={{ fontSize: 13, marginTop: 4 }} className={m.role === 'system' ? 'mono muted' : ''}>{m.text}</div>)}
            {(phase === 'done' || phase === 'world') && (
              <div className="reasons">
                {brief && <div className="reason"><b>Brief</b><span>{brief.panels.map((x) => x.title).join(' and ') || 'status, glance numbers and the attention list'}{brief.reason ? `, because ${brief.reason}` : ''}</span></div>}
                {activity.map((p) => <div key={p.id} className="reason"><b>{p.title}</b><span>{p.reason ? `because ${p.reason}` : p.description}</span></div>)}
              </div>
            )}
          </Step>
          <Step n={5} title="Laying out the World" state={phase === 'done' ? 'done' : phase === 'world' ? 'active' : 'todo'}>
            {phase === 'world' && <span className="mono" style={{ color: 'var(--accent)' }}>placing units…</span>}
            {phase === 'done' && world && (
              <div className="reasons">
                <div className="reason"><b>{world.shape.replace('_', ' ')} world</b><span>{world.reasons?.shape ?? ''}</span></div>
                <div className="reason"><b>Distance</b><span>{world.metric?.sentence}</span></div>
                <div className="reason"><b>Units</b><span>{world.reasons?.render ?? world.render?.tier}</span></div>
                {world.unavailable?.length > 0 && <div className="reason"><b>Not shown</b><span>{world.unavailable.slice(0, 3).map((u: string) => u.split(':')[0]).join('; ')}</span></div>}
              </div>
            )}
          </Step>
          <Step n={6} title="Explaining it to you" state={phase === 'done' ? (orient ? 'done' : 'active') : 'todo'}>
            {phase === 'done' && orient && <StudyGuide o={orient} />}
          </Step>
          {phase === 'done' && !live && play && <div className="muted" style={{ fontSize: 13, padding: '0 0 6px 36px' }}>Opens {play}. Everything here can be changed from Edit on any page.</div>}
          <div className="row" style={{ padding: '12px 0 14px', gap: 10 }}>
            <button className="btn ghost" onClick={onBack}>Back</button>
            <span style={{ flex: 1 }} />
            <button className={`btn ${phase === 'done' ? 'accent' : ''}`} onClick={onDone}>Open the dashboard <Icon name="arrow" size={14} /></button>
          </div>
        </div>
        <ProfileView prof={prof} />
      </div>
    </div>
  )
}
