export async function get<T = any>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export async function post<T = any>(path: string, body: unknown = {}): Promise<T> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export async function del<T = any>(path: string): Promise<T> {
  const r = await fetch(path, { method: 'DELETE' })
  return r.json()
}

export const api = {
  clock: (action: string, value?: number) => post('/api/clock', { action, value }),
  clockJump: (to: string) => post('/api/clock', { action: 'jump', to }),
  question: (text: string, scope?: string | null, kind = 'general') => post('/api/question', { text, scope, kind }),
  directive: (kind: string, scope: string | null, payload: Record<string, unknown> = {}, reason = '') =>
    post('/api/directive', { kind, scope, payload, reason }),
  approve: (id: string, approve: boolean) => post(`/api/directive/${id}/approve`, { approve }),
  pin: (text: string, kind = 'pinned_fact', evidence: string[] = []) => post('/api/ledger/pin', { text, kind, evidence }),
  unpin: (id: string) => del(`/api/ledger/${id}`),
  invAction: (id: string, action: string, extra: Record<string, unknown> = {}) =>
    post(`/api/investigation/${id}/action`, { action, ...extra }),
  config: (changes: Record<string, unknown>) => post('/api/config', changes),
  control: (kind: string, target: string, payload: Record<string, unknown> = {}) =>
    post('/api/control/action', { kind, target, payload }),
  session: (params: Record<string, unknown>) => post('/api/session', params),
}
