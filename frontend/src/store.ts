import { create } from 'zustand'
import type { DashState, Snapshot } from './types'
import { applyTheme } from './theme'

export type Route = 'compose' | 'analyze' | 'brief' | 'attention' | 'world' | 'investigations' | 'control' | 'hood' | 'settings' | 'organization'
  | 'monitor' | `page:${string}`
const ROUTES = ['analyze', 'brief', 'attention', 'world', 'investigations', 'control', 'hood', 'settings', 'organization', 'monitor']

export type StudioTab = 'add' | 'build' | 'ask' | 'history'
export interface Toast { id: number; text: string; undo?: boolean }

export type Drawer =
  | { kind: 'claim'; id: string }
  | { kind: 'event'; id: string }
  | { kind: 'entity'; id: string }
  | { kind: 'scope'; scope: string }
  | { kind: 'finding'; id: string }
  | null

export interface ChatMsg {
  id: string; ts: string; stream_ts: string | null; role: 'viewer' | 'assistant' | 'tool' | 'event' | 'system' | 'approval' | 'narration'
  via: 'copilot' | 'channel' | 'system'; text: string; meta: Record<string, any>; status: string | null
}

interface UIState {
  snap: Snapshot | null
  composed: string | null
  dash: DashState | null
  designing: boolean
  studioOpen: boolean
  studioTab: StudioTab
  studioPage: string | null
  setStudioOpen: (v: boolean, tab?: StudioTab, page?: string | null) => void
  toast: Toast | null
  lensDialog: boolean
  chatDraft: string
  askCopilot: (text: string) => void
  worldFocus: string | null
  showInWorld: (scope: string) => void
  showToast: (text: string, undo?: boolean) => void
  loadDash: () => Promise<void>
  setDash: (d: DashState) => void
  chat: ChatMsg[]
  chatOpen: boolean
  typing: boolean
  setChatOpen: (v: boolean) => void
  setChat: (m: ChatMsg[]) => void
  connected: boolean
  route: Route
  drawer: Drawer
  selectedInvestigation: string | null
  sessionOpen: boolean
  tick: number
  freshBriefing: Set<string>
  setRoute: (r: Route) => void
  openDrawer: (d: Drawer) => void
  selectInvestigation: (id: string | null) => void
  setSessionOpen: (v: boolean) => void
  connect: () => void
}

let ws: WebSocket | null = null
let retry = 0

export const useStore = create<UIState>((set, getState) => ({
  snap: null,
  composed: (() => { try { return sessionStorage.getItem('ss.composed') } catch { return null } })(),
  dash: null,
  designing: false,
  studioOpen: false,
  studioTab: 'add',
  studioPage: null,
  setStudioOpen: (v, tab, page) => set((st) => ({ studioOpen: v, studioTab: tab ?? st.studioTab, studioPage: page === undefined ? st.studioPage : page, ...(v ? { drawer: null, lensDialog: false } : {}) })),
  toast: null,
  lensDialog: false,
  chatDraft: '',
  askCopilot: (text) => set({ chatDraft: text, chatOpen: true }),
  worldFocus: null,
  showInWorld: (scope) => { localStorage.setItem('ss.route', 'world'); set({ worldFocus: scope, route: 'world', drawer: null, studioOpen: false }) },
  showToast: (text, undo = false) => {
    const id = Date.now()
    set({ toast: { id, text, undo } })
    setTimeout(() => { if (getState().toast?.id === id) set({ toast: null }) }, undo ? 7000 : 3500)
  },
  setDash: (dash) => set({ dash, designing: dash.designing }),
  loadDash: async () => {
    try {
      const r = await fetch('/api/dashboard')
      if (r.ok) { const d = await r.json(); set({ dash: d, designing: d.designing }) }
    } catch { /* no session yet */ }
  },
  chat: [],
  chatOpen: localStorage.getItem('ss.chat') !== '0',          // the live column is open unless someone closed it
  typing: false,
  setChatOpen: (v) => { try { localStorage.setItem('ss.chat', v ? '1' : '0') } catch { /* ignore */ } set({ chatOpen: v }) },
  setChat: (chat) => set({ chat }),
  connected: false,
  route: (() => {
    const r = localStorage.getItem('ss.route') || 'brief'
    return (ROUTES.includes(r) || r.startsWith('page:') ? r : 'brief') as Route
  })(),
  drawer: null,
  selectedInvestigation: null,
  sessionOpen: false,
  tick: 0,
  freshBriefing: new Set(),
  setRoute: (route) => { localStorage.setItem('ss.route', route); set({ route, drawer: null, studioOpen: false }) },
  openDrawer: (drawer) => set(drawer ? { drawer, studioOpen: false, lensDialog: false } : { drawer }),
  selectInvestigation: (id) => { localStorage.setItem('ss.route', 'investigations'); set({ selectedInvestigation: id, route: 'investigations', drawer: null }) },
  setSessionOpen: (v) => set(v ? { route: 'compose' } : {}),
  connect: () => {
    if (ws && ws.readyState <= 1) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/ws`)
    ws.onopen = () => { retry = 0; set({ connected: true }) }
    ws.onclose = () => {
      set({ connected: false })
      setTimeout(() => getState().connect(), Math.min(5000, 500 * 2 ** retry++))
    }
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      if (msg.type === 'chat') {
        const m = msg.data as ChatMsg
        if (m.id === 'msg_typing') { set({ typing: !!m.meta?.typing }); return }
        const cur = getState().chat
        const i = cur.findIndex((x) => x.id === m.id)
        set({ chat: i >= 0 ? cur.map((x) => (x.id === m.id ? m : x)) : [...cur, m].slice(-400) })
        return
      }
      if (msg.type === 'dashboard') { getState().loadDash(); return }
      if (msg.type === 'theme') { if (msg.data?.resolved) applyTheme(msg.data.resolved); return }
      if (msg.type === 'escalation') {
        const d = msg.data as { id: string; level: string; title: string; by: string }
        getState().showToast(`${d.level === 'PAGE' ? 'Act now' : 'Needs a decision'} · ${d.by}: ${d.title}`)
        return
      }
      if (msg.type === 'dashboard_designing') { set({ designing: !!msg.data?.on }); return }
      if (msg.type === 'snapshot') {
        const prev = getState().snap
        if (!prev || prev.source?.id !== msg.data.source?.id || (prev.dashboard_version ?? -1) !== (msg.data.dashboard_version ?? -1)) {
          setTimeout(() => getState().loadDash(), 0)
        }
        const known = new Set((prev?.briefing ?? []).map((b) => b.id))
        const fresh = new Set((msg.data.briefing ?? []).filter((b: any) => prev && !known.has(b.id)).map((b: any) => b.id))
        set({ snap: msg.data, tick: getState().tick + 1, freshBriefing: fresh as Set<string> })
      }
    }
  },
}))

/** Re-fetch view data whenever a new snapshot arrives (throttled by the caller's deps). */
export const useTick = () => useStore((s) => s.tick)
