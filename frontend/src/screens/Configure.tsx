import React, { useEffect, useState } from 'react'
import { api, get } from '../api'
import type { Snapshot } from '../types'
import { Icon, Panel, Seg, Toggle } from '../components/ui'

interface Registry {
  monitors: { id: string; title: string; description: string; requires: string[]; optional: string[]; watchers: string[]
    available: boolean; missing: string[]; enabled: boolean; slots: Record<string, string>; tunables: Record<string, number[]> }[]
  slots: Record<string, { id: string; doc: string }[]>
  executive_strategies: string[]; risk_policies: string[]; autonomy: string[]; llm_modes: string[]
  org: any; profile: any
}

const SLOT_ORDER = ['retrieval', 'summarization', 'evaluation', 'escalation', 'critique']
const STRATEGY_DOC: Record<string, string> = {
  agent_org: 'A main agent that spawns, steers and retires structured sub-agents, defined by a topology (Organization screen).',
  structured_state: 'Stateless call: state object in, state object out. Inspectable and replayable.',
  persistent_session: 'A long-lived Claude Code session keeps its own memory; the state object is still written.',
  hierarchical_summary: 'Keeps a tree of period summaries and consults them each step.',
  ensemble: 'Two executives; directives both agree on are applied, disagreement is reported.',
  deterministic: 'Rule-based executive. No model; the baseline every LLM strategy is compared with.',
  global_summary: 'Baseline: one summarizer reads raw recent events. No monitors feed it.',
}

export function Configure({ s }: { s: Snapshot }) {
  const [reg, setReg] = useState<Registry | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const load = () => get<Registry>('/api/registry').then(setReg)
  useEffect(() => { load() }, [s.source.id, s.org.id])
  if (!reg) return null
  const org = reg.org
  const apply = async (changes: Record<string, unknown>, note: string) => {
    await api.config(changes); await load(); setSaved(note); setTimeout(() => setSaved(null), 2200)
  }
  const enabled = reg.monitors.filter((m) => m.enabled).map((m) => m.id)
  return (
    <div className="fade-in">
      <div className="row" style={{ alignItems: 'flex-end', marginBottom: 6 }}>
        <div className="page-title">Configure the organization</div>
        {saved && <span className="chip soft st-OBSERVED" style={{ marginLeft: 12 }}><span className="dot" />{saved}</span>}
      </div>
      <div className="muted" style={{ marginBottom: 18, maxWidth: 780 }}>
        Every part of the monitoring organization is swappable: which monitors run, the strategy in each of their five slots, how the
        Executive thinks, how much autonomy it has, and how risk maps to action. Changes apply from the next window.
      </div>

      <div className="grid">
        <Panel title="Autonomy & models" className="span-6">
          <div className="stack" style={{ gap: 14 }}>
            <Field label="Autonomy" doc="Observe records the Executive's directives; Assisted waits for your approval; Auto applies them.">
              <Seg value={org.autonomy} onChange={(v) => apply({ autonomy: v }, 'autonomy updated')}
                options={[{ v: 'observe', l: 'Observe' }, { v: 'assisted', l: 'Assisted' }, { v: 'auto_investigate', l: 'Auto investigate' }]} />
            </Field>
            <Field label="LLM mode" doc="Deterministic runs everything without a model. Cheap uses Sonnet 5.5 at low effort through your Claude Code login. Full uses per-role models.">
              <Seg value={org.llm?.mode ?? 'stub'} onChange={(v) => apply({ 'llm.mode': v }, `LLM mode: ${v}`)}
                options={[{ v: 'stub', l: 'Deterministic' }, { v: 'cheap', l: 'Cheap' }, { v: 'full', l: 'Full' }]} />
            </Field>
            <Field label="Risk policy" doc="Maps the risk vector to WATCH / INVESTIGATE / ALERT / PAGE.">
              <Seg value={org.risk_policy} onChange={(v) => apply({ risk_policy: v }, 'risk policy updated')}
                options={reg.risk_policies.map((p) => ({ v: p, l: p.replace('_', ' ') }))} />
            </Field>
          </div>
        </Panel>
        <Panel title="Executive" className="span-6" kicker="the master role">
          <div className="stack" style={{ gap: 12 }}>
            <div className="grid" style={{ gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 8 }}>
              {reg.executive_strategies.map((st) => (
                <button key={st} className="card" style={{ textAlign: 'left', cursor: 'pointer', borderColor: org.executive?.strategy === st ? 'var(--ink)' : undefined }}
                  onClick={() => apply({ 'executive.strategy': st }, `executive: ${st}`)}>
                  <div style={{ fontWeight: 600 }}>{st.replace(/_/g, ' ')}</div>
                  <div className="muted" style={{ fontSize: 12 }}>{STRATEGY_DOC[st]}</div>
                </button>
              ))}
            </div>
            <div className="row" style={{ gap: 18 }}>
              <Num label="Cadence (windows)" value={org.executive?.cadence_windows} min={1} max={48} onChange={(v) => apply({ 'executive.cadence_windows': v }, 'cadence updated')} />
              <Num label="Ledger budget (tokens)" value={org.executive?.ledger_token_budget} min={500} max={30000} step={500} onChange={(v) => apply({ 'executive.ledger_token_budget': v }, 'ledger budget updated')} />
              <Num label="Max focuses" value={org.executive?.directives?.max_active_focuses} min={0} max={20} onChange={(v) => apply({ 'executive.directives.max_active_focuses': v }, 'focus budget updated')} />
            </div>
          </div>
        </Panel>

        <Panel title="Budgets" className="span-12">
          <div className="row" style={{ gap: 28, flexWrap: 'wrap' }}>
            <Num label="Max active investigations" value={org.investigations?.max_active} min={0} max={10} onChange={(v) => apply({ 'investigations.max_active': v }, 'investigation budget updated')} />
            <Num label="Budget per investigation ($)" value={org.investigations?.budget_usd_per_investigation} min={0.05} max={5} step={0.05} onChange={(v) => apply({ 'investigations.budget_usd_per_investigation': v }, 'budget updated')} />
            <Num label="Max LLM spend per hour ($)" value={org.budgets?.max_usd_per_hour} min={0.1} max={50} step={0.1} onChange={(v) => apply({ 'budgets.max_usd_per_hour': v }, 'spend cap updated')} />
            <Num label="Max investigation depth" value={org.investigations?.max_depth} min={1} max={5} onChange={(v) => apply({ 'investigations.max_depth': v }, 'depth updated')} />
          </div>
        </Panel>

        <div className="span-12">
          <div className="h-section" style={{ margin: '6px 0 10px' }}>Monitors</div>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))' }}>
            {reg.monitors.map((m) => (
              <section key={m.id} className="panel" style={{ opacity: m.available ? 1 : 0.55 }}>
                <div className="panel-head">
                  <span className="title">{m.title}</span>
                  <span style={{ marginLeft: 'auto' }}>
                    <Toggle on={m.enabled} label={`toggle ${m.id}`} onChange={(v) => m.available && apply({ monitors: v ? [...enabled, m.id] : enabled.filter((x) => x !== m.id) }, `${m.id} ${v ? 'enabled' : 'disabled'}`)} />
                  </span>
                </div>
                <div className="panel-body">
                  <div className="muted" style={{ fontSize: 13, marginBottom: 8 }}>{m.description}</div>
                  <div className="mono muted" style={{ marginBottom: 10 }}>
                    watchers: {m.watchers.join(', ')}<br />
                    {m.available ? `requires ${m.requires.join(', ')}` : <span style={{ color: 'var(--st-contradicted)' }}>unavailable: source lacks {m.missing.join(', ')}</span>}
                  </div>
                  <div className="stack" style={{ gap: 6 }}>
                    {SLOT_ORDER.map((slot) => (
                      <div key={slot} className="row" style={{ gap: 8 }}>
                        <span className="label" style={{ width: 100 }}>{slot}</span>
                        <select className="input" style={{ padding: '4px 26px 4px 8px', fontSize: 12.5 }} value={m.slots[slot]} disabled={!m.enabled}
                          title={reg.slots[slot].find((x) => x.id === m.slots[slot])?.doc}
                          onChange={(e) => apply({ [`overrides.${m.id}.slots.${slot}`]: e.target.value }, `${m.id}.${slot} → ${e.target.value}`)}>
                          {reg.slots[slot].map((o) => <option key={o.id} value={o.id}>{o.id.replace(/_/g, ' ')}</option>)}
                        </select>
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function Field({ label, doc, children }: { label: string; doc: string; children: React.ReactNode }) {
  return <div><div className="label" style={{ marginBottom: 4 }}>{label}</div>{children}<div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{doc}</div></div>
}

function Num({ label, value, min, max, step = 1, onChange }: { label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void }) {
  const [v, set] = useState(value)
  useEffect(() => set(value), [value])
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span className="label">{label}</span>
      <span className="row" style={{ gap: 6 }}>
        <input className="input" type="number" min={min} max={max} step={step} value={v ?? ''} style={{ width: 96 }}
          onChange={(e) => set(+e.target.value)} onBlur={() => v !== value && onChange(v)}
          onKeyDown={(e) => e.key === 'Enter' && onChange(v)} />
      </span>
    </label>
  )
}
