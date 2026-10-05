import React, { useState } from 'react'
import { useStore } from '../store'
import type { Snapshot } from '../types'
import { fmtNum, Icon, pct, Toggle } from '../components/ui'
import { dashOps, Term } from '../components/kit'
import { PANELS, useCapabilities } from '../panels/panels'

interface Section { id: string; title: React.ReactNode; summary: string; panel?: string; link?: { label: string; route: any }; needs?: string }

/** How the oversight itself is working. Collapsed by default; every header says enough to be read closed. */
export function UnderTheHood({ s }: { s: Snapshot }) {
  const dash = useStore((x) => x.dash)
  const setRoute = useStore((x) => x.setRoute)
  const caps = useCapabilities(s.source.id + s.source.synthetic)
  const [open, setOpen] = useState<Record<string, boolean>>(() => { try { return JSON.parse(localStorage.getItem('ss.hood') || '{}') } catch { return {} } })
  const flip = (id: string) => setOpen((o) => { const n = { ...o, [id]: !o[id] }; try { localStorage.setItem('ss.hood', JSON.stringify(n)) } catch { /* ignore */ } return n })
  const sc = s.scale, t = sc?.triage, cov = sc?.coverage, ag = (s as any).agents
  const hr = t?.hit_rates?.triage
  const sections: Section[] = [
    { id: 'triage', title: <Term k="triage">Reading plan</Term>, panel: 'triage',
      summary: t?.items.length ? `${t.items.length} picks this cycle${hr != null ? `; ${pct(hr)} of priority picks found something` : ''}` : 'no plan yet' },
    { id: 'cohorts', title: <Term k="cohorts">Groups that behave alike</Term>, panel: 'cohorts',
      summary: sc ? `${sc.population.cohorts} group${sc.population.cohorts === 1 ? '' : 's'} covering ${fmtNum(sc.population.units_active)} active ${sc.population.unit === 'actor' ? s.source.noun : (s.brief?.terms.resource ?? 'resource')}s; ${sc.population.outliers} stand${sc.population.outliers === 1 ? 's' : ''} out` : 'no groups yet' },
    { id: 'coverage', title: <Term k="coverage_ledger">What we have read</Term>, panel: 'coverage',
      summary: cov ? `${cov.cohorts_looked_at_now} of ${cov.cohorts} groups read this cycle${cov.unassigned_picks.length ? `; ${cov.unassigned_picks.length} picks had nobody to read them` : ''}` : 'nothing read yet' },
    { id: 'organization', title: <Term k="organization">The analyst team</Term>, panel: 'organization', link: { label: 'Open the full team view', route: 'organization' },
      summary: ag ? `${ag.tree?.length ?? 0} analyst${(ag.tree?.length ?? 0) === 1 ? '' : 's'} over ${sc?.divisions ?? 0} division${sc?.divisions === 1 ? '' : 's'}${sc?.sectors ? ` in ${sc.sectors} sectors` : ''}${ag.running ? ` · ${ag.running} reading now` : ''}` : 'not started' },
    { id: 'health', title: <Term k="health">Monitor health</Term>, panel: 'health',
      summary: `${pct(s.health.coverage)} read closely · ${s.health.blind_spots} not yet read${s.health.errors.length ? ` · ${s.health.errors.length} errors` : ''}` },
    { id: 'monitor_attention', title: 'Where monitoring effort goes', panel: 'monitor_attention', link: { label: 'Open effort and suggestions', route: 'monitor' },
      summary: s.attention.by_scope[0] ? `most effort on ${/^division:|^sector:|div_/.test(s.attention.by_scope[0].label) ? 'one analyst division' : s.attention.by_scope[0].label}` : 'no effort spent yet' },
    { id: 'executive', title: 'What SwarmFrame believes', panel: 'executive',
      summary: `${s.executive.hypotheses.length} hypotheses · ${s.ledger.entries.length} things kept in mind` },
    { id: 'templates', title: <Term k="template">Message types</Term>, panel: 'templates', needs: 'artifacts',
      summary: sc?.population.messages ? `${fmtNum(sc.population.messages)} texts in ${sc.population.templates} shapes (wording hidden)` : 'no texts yet' },
    { id: 'cost', title: 'Cost and models', summary: `$${s.health.spent_usd.toFixed(2)} spent · ${s.org.llm_mode === 'stub' ? 'models off (deterministic analysts, no cost)' : `models on (${s.org.llm_mode})`}`,
      link: { label: 'Change in Settings', route: 'settings' } },
  ]
  return (
    <div className="fade-in narrow">
      <header className="page-head">
        <div>
          <h1 className="page-title">Under the hood</h1>
          <p className="page-sub">How the oversight itself is working: what the analysts read, how they group the population, and what it costs.
            Any of these can also go on any page from Edit.</p>
        </div>
        {dash && (
          <label className="row machinery-switch">
            <Toggle on={dash.spec.machinery} onChange={(v) => dashOps([{ op: 'set_machinery', on: v }], v ? 'showed the machinery' : 'hid the machinery', v ? 'Added “The machinery” under Activity' : 'Removed “The machinery”')} />
            <span>Show as a page under Activity</span>
          </label>
        )}
      </header>
      <div className="hood">
        {sections.filter((x) => !x.needs || caps?.[x.needs]?.present).map((x) => {
          const def = x.panel ? PANELS.find((p) => p.id === x.panel) : undefined
          const isOpen = !!open[x.id]
          return (
            <section key={x.id} className={`hood-sec ${isOpen ? 'open' : ''}`}>
              <button className="hood-head" onClick={() => flip(x.id)} aria-expanded={isOpen}>
                <span className="chev"><Icon name="chevron" size={14} /></span>
                <span className="hood-title">{x.title}</span>
                <span className="hood-sum">{x.summary}</span>
              </button>
              {isOpen && (
                <div className="hood-body">
                  {def && def.render(s)}
                  {x.link && <button className="link" style={{ marginTop: 10 }} onClick={() => setRoute(x.link!.route)}>{x.link.label} <Icon name="arrow" size={13} /></button>}
                </div>
              )}
            </section>
          )
        })}
      </div>
    </div>
  )
}
