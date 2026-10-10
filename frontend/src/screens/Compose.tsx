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

type Choice = 'stream' | 'village' | 'transluce' | 'german'
const CHOICE_NAME: Record<Choice, string> = { stream: 'your event stream', village: 'the AI Village week', transluce: 'the Transluce catalog', german: 'the German message board' }
const SRC: Record<Choice, string> = { village: 'ai_village', transluce: 'transluce', german: 'german_wiki', stream: 'generic_stream' }
type TeamLib = { topologies: { id: string; title: string; description: string; roles: number }[]; pack_defaults: Record<string, { topology: string; preset?: string | null; reason: string }> }
interface Info { root: string; hook_script: string; python: string; url: string }
interface Slice { goal: string; start: string; days: number; chat: number; sessions: number; agents: number; title: string }

const LIVE_MIN_EVENTS = 150
const STEPS = ['Pick the data', 'An agent reads it', 'It builds your dashboard', 'You watch, it reports']

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
  const [stage, setStage] = useState<'choose' | 'compose'>('choose')
  const [sources, setSources] = useState<SourceInfo[]>([])
  const [orgs, setOrgs] = useState<{ id: string; name: string }[]>([])
  const [slices, setSlices] = useState<Slice[]>([])
  const [info, setInfo] = useState<Info | null>(null)
  const [choice, setChoice] = useState<Choice>('village')
  const [demo, setDemo] = useState(false)
  const [goal, setGoal] = useState('680a1b42')
  const [org, setOrg] = useState('default')
  const [reading, setReading] = useState<Reading>(DEFAULT_READING)
  const [cadence, setCadence] = useState<Cadence>(DEFAULT_CADENCE)
  const [team, setTeam] = useState<string>('auto')
  const [teams, setTeams] = useState<TeamLib | null>(null)
  const [focus, setFocus] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [setup, setSetup] = useState(false)
  const [morePresets, setMorePresets] = useState(false)
  const [speed, setSpeed] = useState<number | 'max' | null>(null)     // null: the source's recommended speed
  const [play, setPlay] = useState<'live' | 'replay'>('live')
  const [gwFull, setGwFull] = useState(false)     // German board: the June surge (default) or the whole record

  useEffect(() => {
    get('/api/sources').then(setSources).catch(() => {})
    get('/api/orgs').then(setOrgs).catch(() => {})
    get('/api/sources/ai_village/slices').then(setSlices).catch(() => {})
    get('/api/compose/info').then(setInfo).catch(() => {})
    get('/api/agents/topologies').then(setTeams).catch(() => {})
  }, [])
  const has = (id: string) => sources.find((s) => s.id === id)?.has_data
  const packDefault = teams?.pack_defaults?.[SRC[choice]]
  const presetId = packDefault?.preset && packDefault.preset !== 'auto' ? packDefault.preset : null
  const teamTitle = (id: string) => teams?.topologies.find((t) => t.id === id)?.title ?? id
  const autoLabel = teamTitle(packDefault?.topology ?? 'lead')
  const replaySrc = choice === 'stream' ? undefined : sources.find((s) => s.id === SRC[choice])
  const replayHours = choice === 'german' && gwFull ? replaySrc?.replay_hours_full ?? replaySrc?.replay_hours : replaySrc?.replay_hours
  const speeds = replaySrc?.speeds ?? []
  const liveOk = !!replaySrc?.live_stretch && !(choice === 'village' && goal !== '680a1b42')
  const recommended = (replaySrc?.autoplay ?? null) as number | 'max' | null
  const chosen = speed ?? recommended
  useEffect(() => { setSpeed(null) }, [choice])
  useEffect(() => { if (replaySrc) setPlay(replaySrc.play_default === 'replay' ? 'replay' : 'live') }, [choice, replaySrc?.id])
  const running = snap && !snap.empty ? snap : null
  const liveNow = liveOk && play === 'live'

  const start = async () => {
    setBusy(true); setErr('')
    const p: Record<string, any> = { org, overrides: { ...readingOverrides(reading), ...(team !== 'auto' ? { 'agents.topology': team } : {}) },
      ...(speed != null && replaySrc && !liveNow ? { speed } : {}), ...(liveNow ? { live: true, autoplay: true } : {}) }
    if (choice === 'stream') Object.assign(p, { source: 'generic_stream', demo_feed: demo ? { agents: 400, hours: 10, speed: 240 } : undefined })
    else if (choice === 'village') Object.assign(p, { source: 'ai_village', goal })
    else if (choice === 'german') Object.assign(p, { source: 'german_wiki', ...(gwFull ? { slice: { full: true } } : {}) })
    else Object.assign(p, { source: 'transluce' })
    try {
      await api.session(p)
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
      <span className={`radio ${choice === id ? 'on' : ''}`} aria-hidden />
      <div style={{ minWidth: 0 }}>
        <div className="sc-title">{title}</div>
        <div className="sc-body">{body}</div>
      </div>
      <span className="label sc-meta">{meta}</span>
      {choice === id && children && <div className="sc-more" onClick={(e) => e.stopPropagation()}>{children}</div>}
    </div>
  )
  const reader = reading.provider === 'none' ? 'Rules only, no model' : `${prettyModel(reading.primary.model)} lead, ${prettyModel(reading.subagents.model)} explorers`
  const playLine = choice === 'stream' ? 'Live as events arrive' : liveNow ? `Watch ${replaySrc?.live_stretch?.label ?? 'the busiest stretch'} live`
    : `Replay${chosen ? ` at ${fmtRate(chosen as number | 'max')}` : ''}`
  const updates = cadence.narrate === 0 ? 'Updates every window' : cadence.narrate === 60 ? 'Updates every minute' : 'Updates every 5 minutes'

  return (
    <div className="compose fade-in">
      <section className="compose-hero">
        <SwarmField input={DEMO_FIELD} />
        <h1 className="compose-title">What should we watch?</h1>
        <p className="compose-lede">Pick a source and press Start. An agent reads the data, builds a dashboard for it, and keeps telling you what is going on.</p>
        <div className="steps-line" aria-label="How SwarmFrame works">
          {STEPS.map((t, i) => <React.Fragment key={t}>{i > 0 && <span className="sep">→</span>}<span><b>{i + 1}</b>{t}</span></React.Fragment>)}
        </div>
      </section>

      {running && (
        <div className="card row running-card">
          <span className="live-dot run" />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600 }}>Running now: {running.source.title}</div>
            <div className="muted" style={{ fontSize: 12.5 }}>{running.org.llm_label?.short ?? (running.org.llm_mode === 'stub' ? 'rules only' : 'Claude')}</div>
          </div>
          <button className="btn primary" onClick={() => open(running)}>Back to the dashboard <Icon name="arrow" size={14} /></button>
        </div>
      )}

      <div className="section-label"><span className="label">The data</span><span className="muted" style={{ fontSize: 12.5 }}>a live stream of your own, or a recorded swarm</span></div>
      <div className="source-list-c" role="radiogroup" aria-label="Source">
        {card({ id: 'stream', meta: 'live · any source', title: 'Your own event stream', body: 'Post JSON events from any swarm. SwarmFrame works out what your stream contains from what arrives and builds the dashboard around it.', children: <>
          <div className="muted" style={{ fontSize: 12.5 }}>POST a JSON list to <span className="mono">{info?.url ?? 'http://127.0.0.1:8765'}/ingest/events</span>. Only <b>action</b> is required; every other field adds what the dashboard can show.</div>
          <pre className="code-box">{`[{"ts": "2026-10-03T14:05:00Z", "actor": "agent-17", "group": "team-a",
  "action": "tool.write", "object": "repo/README.md", "family": "files",
  "text": "optional agent-written text"}]`}</pre>
          <label className="row" style={{ gap: 6, fontSize: 13 }}><input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} />Play a sample swarm into it (400 agents)</label>
        </> })}
        {card({ id: 'village', meta: has('ai_village') ? 'recorded · real' : 'recorded · not downloaded', title: 'AI Village', body: 'Twenty-one AI agents with their own computers and a shared chat, working toward a common goal for a week.', children: <>
          <select className="input" value={goal} onChange={(e) => setGoal(e.target.value)} aria-label="Goal period">
            {[...slices].sort((a, b) => (b.goal.startsWith('680a1b42') ? 1 : 0) - (a.goal.startsWith('680a1b42') ? 1 : 0)).map((s) => <option key={s.goal} value={s.goal.slice(0, 8)}>{s.goal.startsWith('680a1b42') ? 'Recommended · ' : ''}{s.start.slice(0, 10)} · {s.days} days · {s.agents} agents · {s.chat} messages</option>)}
            {!slices.length && <option value="680a1b42">The recommended week</option>}
          </select>
        </> })}
        {card({ id: 'german', meta: has('german_wiki') ? 'recorded · real' : 'recorded · stand-in', title: 'The German message board', body: 'Handles writing on a shared wiki, groups converging on the same pages, text spreading between them, and moderators deleting pages in sweeps.', children: <>
          <div className="seg sm">
            <button className={!gwFull ? 'on' : ''} onClick={() => setGwFull(false)}>The June surge · Jun 10–25</button>
            <button className={gwFull ? 'on' : ''} onClick={() => setGwFull(true)}>Whole record · May 17–Jul 14</button>
          </div>
        </> })}
        {card({ id: 'transluce', meta: has('transluce') ? 'recorded · real' : 'recorded · stand-in', title: 'Agent activity on the web', body: "Transluce's catalog of 37,649 web-scan reports attributed to autonomous agents: what each targeted, how, and how sure the attribution is." })}
      </div>

      <section className="surface runbar">
        <div className="run-summary">
          <span className="label" style={{ marginRight: 4 }}>How it runs</span>
          <span className="pill">{reader}</span>
          <span className="pill">{team === 'auto' ? autoLabel : team === 'composed' ? 'Composed for this data' : teamTitle(team)}</span>
          <span className="pill">{playLine}</span>
          <span className="pill">{updates}</span>
          <button className="link" onClick={() => setSetup(!setup)} aria-expanded={setup}>{setup ? 'Done' : 'Change'}</button>
        </div>
        {setup && (
          <div className="setup">
            <div>
              <div className="setup-h"><span className="label">Who does the reading</span><span className="muted">the analysts, the composer and the assistant in the live column</span></div>
              <ReaderPicker value={reading} onChange={setReading} />
            </div>
            <div>
              <div className="setup-h"><span className="label">The analyst team</span></div>
              <div className="team-pick" role="radiogroup" aria-label="Team">
                <button role="radio" aria-checked={team === 'auto'} className={`team-opt ${team === 'auto' ? 'on' : ''}`} onClick={() => setTeam('auto')}>
                  <span className="team-top"><span className="mode-dot" />{autoLabel}<span className="mode-cost">default</span></span>
                  <span className="mode-body">{TEAM_PLAIN[packDefault?.topology ?? 'lead'] ?? TEAM_PLAIN.lead}</span>
                </button>
                <button role="radio" aria-checked={team === 'composed'} className={`team-opt ${team === 'composed' ? 'on' : ''}`} onClick={() => setTeam('composed')}>
                  <span className="team-top"><span className="mode-dot" />Composed for this data<span className="mode-cost">new</span></span>
                  <span className="mode-body">A lead with explorers, plus readers and specialists switched on by what the records show (self-reports, shared text, moderation, look-alike names), each with its reason.</span>
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
              <button className="link" style={{ marginTop: 8 }} onClick={() => setMorePresets(!morePresets)}>{morePresets ? 'Fewer team shapes' : 'More team shapes'}</button>
            </div>
            {liveOk && replaySrc?.live_stretch && (
              <div>
                <div className="setup-h"><span className="label">How to play it</span></div>
                <div className="mode-pick two">
                  <button className={`mode-opt ${play === 'live' ? 'on' : ''}`} onClick={() => setPlay('live')}>
                    <span className="mode-top"><span className="mode-dot" />Watch live<span className="mode-cost">real time</span></span>
                    <span className="mode-body">{replaySrc.live_stretch.label ? `${replaySrc.live_stretch.label[0].toUpperCase()}${replaySrc.live_stretch.label.slice(1)}` : 'The busiest real stretch'}, as it happened ({replaySrc.live_stretch.rate}), after a short catch-up.</span>
                  </button>
                  <button className={`mode-opt ${play === 'replay' ? 'on' : ''}`} onClick={() => setPlay('replay')}>
                    <span className="mode-top"><span className="mode-dot" />Replay the record<span className="mode-cost">faster</span></span>
                    <span className="mode-body">The whole period, sped up, from start to end.</span>
                  </button>
                </div>
              </div>
            )}
            {replaySrc && speeds.length > 0 && !liveNow && (
              <div>
                <div className="setup-h"><span className="label">Replay speed</span><span className="muted">change it any time from the top bar</span></div>
                <div className="speed-pick">
                  {[...speeds, { v: 1, label: 'Real time', note: 'the recorded pace' }].map((o) => (
                    <button key={String(o.v)} className={`speed-opt ${chosen === o.v ? 'on' : ''}`} onClick={() => setSpeed(o.v as number | 'max')} title={o.note}>
                      <span className="speed-l">{o.label}{o.v === recommended && <span className="speed-rec">recommended</span>}</span>
                      <span className="speed-r">{fmtRate(o.v as number | 'max')}</span>
                      <span className="speed-e">{estimate(replayHours, o.v as number | 'max')}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div>
              <div className="setup-h"><span className="label">How often it reports</span><span className="muted">new findings always appear at once</span></div>
              <CadencePicker value={cadence} onChange={setCadence} models={reading.provider !== 'none'} />
            </div>
            {orgs.length > 1 && (
              <div>
                <div className="setup-h"><span className="label">Monitoring organization</span><span className="muted">the default is what the rest of the dashboard assumes; the others are baselines</span></div>
                <select className="input" value={org} onChange={(e) => setOrg(e.target.value)} style={{ maxWidth: 320 }}>
                  {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
              </div>
            )}
          </div>
        )}
        <div className="run-actions">
          <input className="input" value={focus} onChange={(e) => setFocus(e.target.value)} aria-label="Anything to focus on (optional)"
            placeholder="Anything to focus on? (optional) e.g. which teams converge on shared files" />
          <button className="btn accent lg" disabled={busy} onClick={start}>{busy ? 'Connecting…' : 'Start'} <Icon name="arrow" size={15} /></button>
        </div>
        <div className="muted" style={{ fontSize: 12.5 }}>
          An agent reads {CHOICE_NAME[choice]}, builds a dashboard, then {choice === 'stream' ? 'watches it live' : liveNow ? 'plays the stretch in real time' : 'replays the record'} and explains what it built in the live column.
        </div>
        {err && <div className="mono" style={{ color: 'var(--st-contradicted)' }}>{err}</div>}
      </section>

      <div className="side-card">
        <span className="side-icon"><Icon name="file" /></span>
        <div>
          <div style={{ fontWeight: 600 }}>Have a dump instead?</div>
          <div className="muted" style={{ fontSize: 13 }}>Analyze a folder or file of logs after the fact (JSON, JSON lines, CSV, gzipped or zipped) and get a written report with sources. No live monitoring.</div>
        </div>
        <button className="btn" onClick={() => setRoute('analyze')}>Analyze a dump <Icon name="arrow" size={14} /></button>
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
    <div className="compose-step">
      <span className={`n ${state === 'todo' ? '' : state}`}>{state === 'done' ? '✓' : n}</span>
      <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 600 }}>{title}</div><div style={{ marginTop: 4 }}>{children}</div></div>
    </div>
  )
  return (
    <div className="compose fade-in" style={{ maxWidth: 1180 }}>
      <div className="label" style={{ marginBottom: 6 }}>{snap.source.title}</div>
      <div className="compose-title" style={{ fontSize: 'calc(34px * var(--headline))' }}>{phase === 'done' ? 'Your dashboard is ready.' : phase === 'world' ? 'Laying out the World…' : 'Composing a dashboard around this stream…'}</div>
      <div className="two-col" style={{ gridTemplateColumns: 'minmax(0, 6fr) minmax(0, 5fr)' }}>
        <div className="surface" style={{ padding: '6px 18px' }}>
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
