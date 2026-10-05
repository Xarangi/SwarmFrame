import React, { useEffect, useState } from 'react'
import { get } from '../api'

/** Who reads the stream (provider, the lead's model, the explorers' model), which team, and how often it reports.
 *  Used by compose mode; the result becomes session overrides plus live-column settings. */

export interface LlmOptions {
  providers: { id: string; label: string; detail: string; available: boolean; why_not?: string }[]
  models: { id: string; label: string; note: string }[]
  efforts: string[]
  defaults: { primary: { model: string; effort: string }; subagents: { model: string; effort: string } }
}
export interface Reading {
  provider: string
  primary: { model: string; effort: string }
  subagents: { model: string; effort: string }
}
export interface Cadence { narrate: number; commentary: number }

export const DEFAULT_READING: Reading = { provider: 'none', primary: { model: 'claude-sonnet-5-5', effort: 'medium' }, subagents: { model: 'claude-sonnet-5-5', effort: 'low' } }
export const DEFAULT_CADENCE: Cadence = { narrate: 60, commentary: 300 }

export function readingOverrides(r: Reading): Record<string, any> {
  if (r.provider === 'none') return { 'llm.mode': 'stub' }
  return { 'llm.mode': 'custom', 'llm.primary': { backend: 'claude_code', ...r.primary }, 'llm.subagents': r.subagents }
}

export const modelLabel = (opts: LlmOptions | null, id: string) => opts?.models.find((m) => m.id === id)?.label.replace('Claude ', '') ?? prettyModel(id)
/** 'claude-haiku-4-5-20251001' -> 'Haiku 4.5' */
export const prettyModel = (id: string) => {
  const m = id.replace(/^claude-/, '').replace(/-\d{8}$/, '').match(/^([a-z]+)-(\d+)-(\d+)$/)
  return m ? `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}.${m[3]}` : id
}

/** Plain descriptions of the team presets (the topology files describe them for engineers). */
export const TEAM_PLAIN: Record<string, string> = {
  lead: 'One lead analyst watches everything. When an area starts to look interesting, it sends an explorer to look into it, reads what the explorer finds, and lets it go once things calm down. The team grows only where something is happening.',
  triage_tree: 'For very large swarms. Code first groups similar agents together; a director then spends a fixed reading budget across the groups (most urgent first, plus neglected ones and a random spot-check), and analysts each cover a few groups.',
  desks: 'For tens of named agents that talk a lot: one analyst per desk of agents, plus standing specialists for honest reporting, copied content and operator actions.',
  board_watch: 'For message boards: analysts per area of the board, a watcher for how writers respond to moderators, and a checker for look-alike names.',
  catalog_review: 'For catalogs of reports with no authors: analysts per group of targets, plus a reviewer that checks the confidence labels.',
  hierarchical_divisions: 'A director over analysts, each covering one part of the population, who can call in specialists.',
  flat_pool: 'A director over one generalist per group, with no specialists. A comparison baseline.',
  single_agent: 'One analyst with all the evidence tools and no team. The baseline for "does a team help?".',
  sdk_native: "One Claude session that delegates with Claude Code's own built-in sub-agents instead of a managed team.",
}

function ModelPick({ label, hint, opts, value, onChange }: { label: string; hint: string; opts: LlmOptions; value: { model: string; effort: string }; onChange: (v: { model: string; effort: string }) => void }) {
  return (
    <div className="model-pick">
      <div className="mp-l">{label}</div>
      <div className="mp-h">{hint}</div>
      <select className="input" value={value.model} onChange={(e) => onChange({ ...value, model: e.target.value })} aria-label={`${label} model`}>
        {opts.models.map((m) => <option key={m.id} value={m.id}>{m.label} · {m.note}</option>)}
      </select>
      <div className="seg sm" style={{ marginTop: 6 }} role="radiogroup" aria-label={`${label} effort`}>
        {opts.efforts.map((x) => <button key={x} className={value.effort === x ? 'on' : ''} onClick={() => onChange({ ...value, effort: x })}>{x} effort</button>)}
      </div>
    </div>
  )
}

export function ReaderPicker({ value, onChange }: { value: Reading; onChange: (r: Reading) => void }) {
  const [opts, setOpts] = useState<LlmOptions | null>(null)
  useEffect(() => { get<LlmOptions>('/api/llm/options').then(setOpts).catch(() => {}) }, [])
  if (!opts) return <div className="muted">Loading the model options…</div>
  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="provider-pick" role="radiogroup" aria-label="Provider">
        {opts.providers.map((p) => (
          <button key={p.id} role="radio" aria-checked={value.provider === p.id} disabled={!p.available}
            className={`mode-opt ${value.provider === p.id ? 'on' : ''}`} onClick={() => onChange({ ...value, provider: p.id })}
            title={p.available ? p.detail : p.why_not}>
            <span className="mode-top"><span className="mode-dot" />{p.label}</span>
            <span className="mode-body">{p.available ? p.detail : p.why_not}</span>
          </button>
        ))}
      </div>
      {value.provider !== 'none' && (
        <div className="model-picks">
          <ModelPick label="Lead agent" hint="Runs the analyst team and is the assistant in the live column that explains what is happening and answers you."
            opts={opts} value={value.primary} onChange={(primary) => onChange({ ...value, primary })} />
          <ModelPick label="Explorers and other sub-agents" hint="Sent by the lead to look into one area each; there can be several at once, so a cheaper model is usual."
            opts={opts} value={value.subagents} onChange={(subagents) => onChange({ ...value, subagents })} />
        </div>
      )}
      {value.provider === 'none' && <div className="muted" style={{ fontSize: 12.5 }}>Fixed rules do all the reading: watchers, a rules-only lead and explorers, and plain-language explanations from templates. Free, but nothing is actually understood.</div>}
    </div>
  )
}

export function CadencePicker({ value, onChange, models }: { value: Cadence; onChange: (c: Cadence) => void; models: boolean }) {
  const N: [number, string][] = [[0, 'Every window'], [60, 'Every minute'], [300, 'Every 5 minutes']]
  const C: [number, string][] = [[300, 'Every 5 minutes'], [900, 'Every 15 minutes'], [0, 'Off']]
  return (
    <div className="cadence-pick">
      <div>
        <div className="mp-l">Activity updates</div>
        <div className="mp-h">A short line in the live column: how much happened, where, and whether it is picking up.</div>
        <div className="seg sm">{N.map(([v, l]) => <button key={v} className={value.narrate === v ? 'on' : ''} onClick={() => onChange({ ...value, narrate: v })}>{l}</button>)}</div>
      </div>
      <div style={{ opacity: models ? 1 : 0.55 }}>
        <div className="mp-l">The lead agent's own summary</div>
        <div className="mp-h">{models ? 'A few plain sentences on what is going on and what matters most. Each one is a model call.' : 'Needs a model (step 2). Findings are still explained as they appear.'}</div>
        <div className="seg sm">{C.map(([v, l]) => <button key={v} disabled={!models} className={value.commentary === v ? 'on' : ''} onClick={() => onChange({ ...value, commentary: v })}>{l}</button>)}</div>
      </div>
    </div>
  )
}
