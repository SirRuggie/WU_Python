import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import {
  activityState, formatCheckedAt, matchingWarActivity, ownAttackText,
  type ActivitySnapshot, type MemberWarActivity,
} from './memberDetailActivity'
import './MemberDetailActivity.css'

export default function MemberDetailActivity({ target, tag, clanTag, onDenied }: {
  target: 'player' | 'clan'
  tag: string
  clanTag?: string | null
  onDenied?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [activity, setActivity] = useState<MemberWarActivity | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [retryAllowed, setRetryAllowed] = useState(false)
  const onDeniedRef = useRef(onDenied)
  onDeniedRef.current = onDenied

  useEffect(() => {
    if (!open) return
    let active = true
    setLoading(true)
    setError('')
    setRetryAllowed(false)
    setActivity(null)
    api<ActivitySnapshot>('/clan-activity?kind=war&scope=mine').then(snapshot => {
      if (!active) return
      setActivity(matchingWarActivity(snapshot, target, tag, clanTag))
    }).catch(reason => {
      if (!active) return
      if (reason instanceof ApiError && [401, 403].includes(reason.status)) {
        setActivity(null)
        setError(reason.message)
        setRetryAllowed(false)
        onDeniedRef.current?.()
      } else {
        setError(reason instanceof Error ? reason.message : 'War activity is unavailable. Try again.')
        setRetryAllowed(true)
      }
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [open, target, tag, clanTag, attempt])

  return <details className="member-detail-activity" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>War &amp; CWL</summary>
    {loading && <p role="status">Loading war activity…</p>}
    {error && <div className="member-detail-activity-error" role="alert"><p>{error}</p>{retryAllowed && <button type="button" onClick={() => setAttempt(value => value + 1)}>Retry war activity</button>}</div>}
    {!loading && !error && activity === null && <p>{target === 'clan' ? 'No member activity returned for this clan.' : 'No activity returned for this account.'}</p>}
    {!loading && !error && activity && <>
      <p className="member-detail-activity-checked">{formatCheckedAt(activity.checkedAt) ? `Checked ${formatCheckedAt(activity.checkedAt)}` : 'Check time unavailable'}</p>
      {activity.warning && <p className="member-detail-activity-warning">{activity.warning}</p>}
      {(['regular', 'cwl'] as const).map((kind, index) => {
        const summary = activity[kind]
        const attackText = target === 'player' ? ownAttackText(summary, tag) : null
        const hostClan = kind === 'regular' ? activity.regularClan : activity.cwlClan
        return <section key={kind} className="member-detail-war">
          <h3>{index === 0 ? 'Regular war' : 'CWL'}</h3>
          <p>{activityState(summary)}</p>
          {hostClan && <p>Hosting clan: {hostClan.name} · {hostClan.tag}</p>}
          {summary && ['preparation', 'inWar', 'warEnded', 'awaitingResult'].includes(String(summary.state)) && <>
            {summary.opponent && typeof summary.opponent === 'object' && <p>Opponent: {String((summary.opponent as {name?: unknown}).name || (summary.opponent as {tag?: unknown}).tag || 'Unknown')}</p>}
            {target === 'clan' && summary.clan && typeof summary.clan === 'object' && <p>Clan score: {String((summary.clan as {stars?: unknown}).stars ?? '—')} stars · {String((summary.clan as {destruction?: unknown}).destruction ?? '—')}% destruction</p>}
            {attackText && <p>{attackText}</p>}
          </>}
        </section>
      })}
    </>}
  </details>
}
