/** The look, applied: the server keeps one checked theme (dashboard/theme.py); this puts it on the page.
 *  Colours, typefaces, density, radius and headline scale become CSS custom properties on :root, and structural
 *  choices become data attributes on <html> that styles.css reads. The last theme is cached so the first paint is
 *  already right. */

export interface ResolvedTheme {
  modes: Record<'light' | 'dark', Record<string, string>>
  mode: 'system' | 'light' | 'dark'
  fonts: { display: string; ui: string; mono: string }
  font_names: { display: string; ui: string; mono: string }
  font_url: string
  vars: Record<string, string>
  attrs: Record<string, string>
}
export interface ThemeSpec {
  preset: string; mode: 'system' | 'light' | 'dark' | null; accent: string | null; fonts: Record<string, string>
  density: string | null; radius: number | null; surface: string | null; canvas: string | null; nav: string | null
  nav_style: string; headline: string; motion: string; labels: string | null
  colors: Record<string, Record<string, string>>; version: number; by: string; rationale: string
}
export interface ThemeState { spec: ThemeSpec; resolved: ResolvedTheme; history: { version: number; by: string; rationale: string }[] }

const VAR: Record<string, string> = {
  bg: '--bg', surface: '--surface', raised: '--raised', sunken: '--sunken', ink: '--ink', ink2: '--ink-2', ink3: '--ink-3',
  ink4: '--ink-4', line: '--line', line2: '--line-2', accent: '--accent', accent_ink: '--accent-ink', accent_soft: '--accent-soft',
  data: '--data', tick: '--tick', grid_dot: '--grid-dot', rail: '--rail', rail2: '--rail-2', rail3: '--rail-3',
  rail_line: '--rail-line', rail_ink: '--rail-ink', rail_ink2: '--rail-ink-2', rail_ink3: '--rail-ink-3', rail_accent: '--rail-accent',
}
const KEY = 'ss.look'
let current: ResolvedTheme | null = null
let media: MediaQueryList | null = null

export function effectiveMode(r: ResolvedTheme | null): 'light' | 'dark' {
  const m = r?.mode ?? 'system'
  if (m === 'light' || m === 'dark') return m
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function paint() {
  const r = current
  const root = document.documentElement
  const mode = effectiveMode(r)
  root.dataset.mode = mode
  if (!r) return
  const t = r.modes[mode]
  for (const [k, v] of Object.entries(VAR)) if (t[k]) root.style.setProperty(v, t[k])
  root.style.setProperty('--font-display', r.fonts.display)
  root.style.setProperty('--font-ui', r.fonts.ui)
  root.style.setProperty('--font-mono', r.fonts.mono)
  root.style.setProperty('--radius', r.vars.radius)
  root.style.setProperty('--radius-sm', r.vars.radius_sm)
  root.style.setProperty('--fs', r.vars.fs)
  root.style.setProperty('--space', r.vars.space)
  root.style.setProperty('--headline', r.vars.headline)
  root.dataset.surface = r.attrs.surface
  root.dataset.canvas = r.attrs.canvas
  root.dataset.nav = r.attrs.nav
  root.dataset.navStyle = r.attrs.nav_style
  root.dataset.motion = r.attrs.motion
  root.dataset.labels = r.attrs.labels
  root.dataset.display = r.attrs.display_kind
}

function loadFonts(url: string) {
  let link = document.getElementById('theme-fonts') as HTMLLinkElement | null
  if (!link) {
    link = document.createElement('link')
    link.id = 'theme-fonts'
    link.rel = 'stylesheet'
    document.head.appendChild(link)
  }
  if (link.href !== url) link.href = url
}

const listeners = new Set<() => void>()
/** Called after every repaint (a change here, from the designer, or from another window). */
export function onTheme(cb: () => void): () => void { listeners.add(cb); return () => { listeners.delete(cb) } }

export function applyTheme(r: ResolvedTheme) {
  current = r
  loadFonts(r.font_url)
  paint()
  listeners.forEach((f) => f())
  try { localStorage.setItem(KEY, JSON.stringify(r)) } catch { /* ignore */ }
}

/** Before React renders: the cached theme, or the system's light/dark. */
export function bootTheme() {
  try { const c = localStorage.getItem(KEY); if (c) current = JSON.parse(c) } catch { /* ignore */ }
  if (current) loadFonts(current.font_url)
  paint()
  media = window.matchMedia?.('(prefers-color-scheme: dark)') ?? null
  media?.addEventListener?.('change', paint)
}

// a handle for screenshot scripts and the console: window.__swarmTheme.fetchTheme() repaints from the server
;(window as any).__swarmTheme = { refresh: () => fetchTheme() }

export async function fetchTheme(): Promise<ThemeState | null> {
  try {
    const r = await fetch('/api/theme')
    if (!r.ok) return null
    const d = (await r.json()) as ThemeState
    applyTheme(d.resolved)
    return d
  } catch { return null }
}

export async function setTheme(changes: Record<string, unknown>, rationale = ''): Promise<ThemeState> {
  const r = await fetch('/api/theme', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ changes, rationale }) })
  const d = await r.json()
  if (!r.ok) throw new Error(d.detail ?? 'not applied')
  applyTheme(d.resolved)
  return d
}

export async function undoTheme(): Promise<ThemeState> {
  const r = await fetch('/api/theme/undo', { method: 'POST' })
  const d = await r.json()
  if (!r.ok) throw new Error(d.detail ?? 'nothing to undo')
  applyTheme(d.resolved)
  return d
}
