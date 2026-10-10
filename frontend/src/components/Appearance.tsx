import { useEffect, useState } from 'react'
import { get, post } from '../api'
import { useStore } from '../store'
import { fetchTheme, onTheme, setTheme, undoTheme, type ThemeState } from '../theme'
import { Icon } from './ui'

/** The look, all of it changeable: describe it in words (the designer), pick a preset, or set each choice by hand.
 *  Every change is checked by the server (readable text, typefaces from a list, meaning colours fixed) and can be
 *  undone. The designer agent works through the same checked settings. */

interface Options {
  presets: Record<string, { title: string; blurb: string; swatches: Record<'light' | 'dark', string[]>; fonts: Record<string, string>; surface: string; nav: string; mode?: string }>
  settings: Record<string, any>
  named_accents: Record<string, { light: string; dark: string }>
  fixed: string[]
  rules: string[]
}

const HINTS = ['Dark, compact, with a teal accent', 'The Paper look with Fraunces headings', 'Console, icons-only sidebar',
  'Clinic, but with a purple accent', 'High contrast, larger text', 'Flat panels, no animation, plain labels']

export function Designer({ scope = 'look', compact = false }: { scope?: 'look' | 'all'; compact?: boolean }) {
  const [text, setText] = useState('')
  const [said, setSaid] = useState('')
  const [busy, setBusy] = useState(false)
  const llm = useStore((x) => x.snap?.org.llm_mode)
  const live = useStore((x) => x.snap && !x.snap.empty)
  const go = async (t = text) => {
    if (!t.trim()) return
    setBusy(true); setSaid('')
    try {
      const r = await post<any>('/api/design', { instruction: t, scope })
      if (r.backend === 'stub' || r.summary) {
        setSaid(r.summary)
        await fetchTheme()
        if (r.applied?.includes('layout')) useStore.getState().loadDash()
        if (r.applied?.length) useStore.getState().showToast('Changed: ' + (r.understood ?? []).join(', '), false)
      } else {
        setSaid('Claude is working on it; progress appears in the live column, and the page updates as each change lands.')
        useStore.getState().setChatOpen(true)
      }
      setText('')
    } catch (e: any) { setSaid(String(e.message || e).replace(/^\d+ /, '')) } finally { setBusy(false) }
  }
  return (
    <div className={`designer-box ${compact ? '' : 'surface'}`}>
      <div className="row" style={{ gap: 8 }}><Icon name="spark" size={16} /><b>{scope === 'look' ? 'Describe the look you want' : 'Describe the change you want'}</b>
        <span className="muted" style={{ fontSize: 12.5 }}>{live && llm !== 'stub' ? 'Claude makes it with checked settings' : 'understood without a model; turn Claude on for anything more'}</span></div>
      <form className="ask-row" onSubmit={(e) => { e.preventDefault(); go() }}>
        <textarea className="input" rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder={scope === 'look' ? 'e.g. darker, with a calmer green accent and less space between panels' : 'e.g. hide the World on the Brief and make it compact'}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go() } }} />
        <button className="btn accent" type="submit" disabled={busy || !text.trim()}>{busy ? 'Working…' : 'Apply'}</button>
      </form>
      <div className="designer-hints">{HINTS.map((h) => <button key={h} className="btn sm ghost" onClick={() => go(h)}>{h}</button>)}</div>
      {said && <div className="designer-said">{said}</div>}
    </div>
  )
}

export function Appearance() {
  const [st, setSt] = useState<ThemeState | null>(null)
  const [opts, setOpts] = useState<Options | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => { fetchTheme().then(setSt); get<Options>('/api/theme/options').then(setOpts).catch(() => {}) }, [])
  // changes made elsewhere (the designer, another window) repaint the page; keep these controls in step
  useEffect(() => onTheme(() => { get<ThemeState>('/api/theme').then(setSt).catch(() => {}) }), [])
  if (!st || !opts) return <div className="skeleton" style={{ height: 300 }} />
  const s = st.spec
  const r = st.resolved
  const set = async (changes: Record<string, unknown>) => {
    setErr('')
    try { setSt(await setTheme(changes)); useStore.getState().showToast('Look changed', false) }
    catch (e: any) { setErr(String(e.message || e)) }
  }
  const undo = async () => { try { setSt(await undoTheme()) } catch (e: any) { setErr(String(e.message || e)) } }
  const fonts = opts.settings.fonts as Record<string, string[]>
  const accents = Object.entries(opts.named_accents)
  const mode = document.documentElement.dataset.mode === 'dark' ? 'dark' : 'light'
  return (
    <div className="appearance">
      <Designer />
      <section>
        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
          <span className="h-section">Start from a look</span>
          <span className="row" style={{ gap: 8 }}>
            <span className="mono muted" style={{ fontSize: 11 }}>version {s.version}{s.by && s.by !== 'default' ? ` · last change by ${s.by === 'human' ? 'you' : s.by}` : ''}</span>
            <button className="btn sm" disabled={!st.history.length} onClick={undo}><Icon name="undo" size={13} />Undo</button>
          </span>
        </div>
        <div className="preset-grid">
          {Object.entries(opts.presets).map(([id, p]) => {
            const [bg, surf, ink, acc] = p.swatches[mode]
            const rail = p.nav === 'dark' ? (mode === 'dark' ? '#050607' : '#15181c') : surf
            return (
              <button key={id} className={`preset-card ${s.preset === id ? 'on' : ''}`} onClick={() => set({ preset: id })}>
                <div className="preset-mini" style={{ background: bg }}>
                  <div className="pm-rail" style={{ background: rail, borderRight: `1px solid ${ink}22` }} />
                  <div className="pm-main">
                    <div className="pm-line" style={{ width: '62%', background: ink, opacity: .85 }} />
                    <div className="pm-line" style={{ width: '40%', background: ink, opacity: .35 }} />
                    <div className="pm-card" style={{ background: surf, border: `1px solid ${ink}1f` }}><span className="pm-dot" style={{ background: acc }} /><span className="pm-line" style={{ width: '50%', background: ink, opacity: .3, height: 4 }} /></div>
                  </div>
                </div>
                <span className="preset-name" style={{ fontFamily: `"${p.fonts.display}", serif` }}>{p.title}</span>
                <span className="preset-blurb">{p.blurb}</span>
              </button>
            )
          })}
        </div>
      </section>
      <section className="surface" style={{ padding: 18 }}>
        <div className="h-section" style={{ marginBottom: 12 }}>Then change anything</div>
        <div className="ctl-grid">
          <div className="ctl"><span className="ctl-h">Light or dark</span><Choice opts={opts} set={set} k="mode" value={s.mode ?? r.mode} labels={{ system: 'Follow the computer' }} /></div>
          <div className="ctl"><span className="ctl-h">Accent</span>
            <div className="swatch-row">
              <button className={`swatch ${!s.accent ? 'on' : ''}`} title="The look's own" style={{ background: opts.presets[s.preset].swatches[mode][3] }} onClick={() => set({ accent: null })} />
              {accents.slice(0, 14).map(([name, c]) => <button key={name} className={`swatch ${s.accent === name ? 'on' : ''}`} title={name} style={{ background: c[mode] }} onClick={() => set({ accent: name })} />)}
              <input type="color" aria-label="Any colour" value={/^#/.test(s.accent ?? '') ? s.accent! : r.modes.light.accent} onChange={(e) => set({ accent: e.target.value })} />
            </div>
            <span className="ctl-note">Used only for actions, the current page and what needs a decision. Finding levels keep their own colours.</span>
          </div>
          {(['display', 'ui', 'mono'] as const).map((role) => (
            <div key={role} className="ctl"><span className="ctl-h">{role === 'display' ? 'Headings' : role === 'ui' ? 'Text' : 'Labels and numbers'}</span>
              <select className="input" value={r.font_names[role]} onChange={(e) => set({ fonts: { [role]: e.target.value } })}>
                {fonts[role].map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
              <span className="font-sample" style={{ fontFamily: r.fonts[role] }}>{role === 'mono' ? '12:04 · 1,284 events' : 'Seven agents converged on one page'}</span>
            </div>
          ))}
          <div className="ctl"><span className="ctl-h">Density</span><Choice opts={opts} set={set} k="density" value={s.density ?? ''} /></div>
          <div className="ctl"><span className="ctl-h">Panels</span><Choice opts={opts} set={set} k="surface" value={r.attrs.surface} labels={{ plate: 'Plates', card: 'Cards', flat: 'Flat', outline: 'Outlined' }} /></div>
          <div className="ctl"><span className="ctl-h">Corners</span>
            <div className="row" style={{ gap: 10 }}><input type="range" min={0} max={18} value={parseInt(r.vars.radius)} onChange={(e) => set({ radius: +e.target.value })} style={{ flex: 1 }} /><span className="mono muted">{r.vars.radius}</span></div></div>
          <div className="ctl"><span className="ctl-h">Background</span><Choice opts={opts} set={set} k="canvas" value={r.attrs.canvas} labels={{ dots: 'Dot grid', grid: 'Line grid', plain: 'Plain' }} /></div>
          <div className="ctl"><span className="ctl-h">Navigation rail</span><Choice opts={opts} set={set} k="nav" value={r.attrs.nav} labels={{ dark: 'Dark', light: 'Matches the page' }} /><Choice opts={opts} set={set} k="nav_style" value={r.attrs.nav_style} labels={{ full: 'Icons and names', icons: 'Icons only' }} /></div>
          <div className="ctl"><span className="ctl-h">Headlines</span><Choice opts={opts} set={set} k="headline" value={s.headline} /></div>
          <div className="ctl"><span className="ctl-h">Labels</span><Choice opts={opts} set={set} k="labels" value={r.attrs.labels} labels={{ mono: 'Mono capitals', sans: 'Plain' }} /></div>
          <div className="ctl"><span className="ctl-h">Motion</span><Choice opts={opts} set={set} k="motion" value={s.motion} labels={{ full: 'Full', reduced: 'Less', none: 'None' }} /></div>
        </div>
        {err && <div className="theme-error" style={{ marginTop: 12 }}>{err}</div>}
        <div className="muted" style={{ fontSize: 12, marginTop: 14 }}>Always checked: {opts.rules.slice(0, 4).join('; ')}. Fixed so findings read the same in every look: {opts.fixed.join('; ')}.</div>
      </section>
    </div>
  )
}

function Choice({ k, value, labels, opts, set }: { k: string; value: string; labels?: Record<string, string>; opts: Options; set: (c: Record<string, unknown>) => void }) {
  return (
    <div className="seg sm wrap">{Object.keys(opts.settings[k] ?? {}).map((v) => (
      <button key={v} className={value === v ? 'on' : ''} title={opts.settings[k][v]} onClick={() => set({ [k]: v })}>{labels?.[v] ?? v[0].toUpperCase() + v.slice(1)}</button>))}</div>
  )
}
