/* Replay speeds: labels and how long the recorded time that holds events takes to play at a given speed. */
export const fmtRate = (v: number | 'max'): string => {
  if (v === 'max' || v >= 1e11) return 'as fast as possible'
  if (v <= 1) return 'real time'
  const u: [number, string][] = [[604800, 'week'], [86400, 'day'], [3600, 'hour'], [60, 'min']]
  for (const [s, n] of u) if (v >= s) { const k = v / s; return `${Number.isInteger(k) ? k : k.toFixed(1)} ${n}${k !== 1 && n !== 'min' ? 's' : ''} per second` }
  return `${v}× real time`
}
export const fmtDuration = (sec: number): string => {
  if (!isFinite(sec)) return ''
  if (sec < 90) return `${Math.max(1, Math.round(sec))} s`
  if (sec < 5400) return `${Math.round(sec / 60)} min`
  if (sec < 86400 * 2) return `${Math.round(sec / 3600)} h`
  return `${Math.round(sec / 86400)} days`
}
/** about how long the whole replay takes; quiet stretches are skipped, and the dashboard reads at most ~60 windows a second */
export const estimate = (hours: number | null | undefined, v: number | 'max'): string => {
  if (!hours) return ''
  if (v === 'max' || v >= 1e11) return 'loads in seconds to a minute'
  return `whole replay ≈ ${fmtDuration((hours * 3600) / v)}`
}
