import { useEffect, useState } from 'react'
import { api } from './api'
import DiscordContact from './DiscordContact'
import './SignupActivity.css'

type Change = {
  id: number; tag: string; player_name: string; user_id: string;
  action: string; from_pool: string; to_pool: string | null;
  assigned_clan_tag: string | null; created_at: string;
}
const poolName = (value: string | null) => value === 'lazy' ? 'Lazy CWL' : 'Main CWL'

export default function SignupActivity({ seasonId }: { seasonId: string }) {
  const [items, setItems] = useState<Change[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<number | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    let fetching = false
    const load = async () => {
      if (fetching) return
      fetching = true
      try {
        const result = await api<{ items: Change[] }>(`/seasons/${encodeURIComponent(seasonId)}/signup-activity`)
        if (active) { setItems(result.items); setError('') }
      } catch (cause) {
        if (active) { setItems([]); setError(cause instanceof Error ? cause.message : 'Could not check signup changes.') }
      } finally { fetching = false; if (active) setLoading(false) }
    }
    void load()
    const timer = window.setInterval(() => { if (!document.hidden) void load() }, 30000)
    return () => { active = false; clearInterval(timer) }
  }, [seasonId, attempt])
  const review = async (id: number) => {
    if (busy !== null) return
    setBusy(id)
    try {
      await api(`/seasons/${encodeURIComponent(seasonId)}/signup-activity/${id}/review`, 'POST')
      setItems(current => current.filter(item => item.id !== id))
      setAttempt(value => value + 1)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not mark reviewed.') }
    finally { setBusy(null) }
  }
  const row = (item: Change) => <article className="signup-activity-row" key={item.id}>
    <div><strong>{item.player_name} · {item.action === 'member_withdrawal' ? 'Withdrew signup' : 'Changed CWL pool'}</strong>
      <p>{item.tag} · {poolName(item.from_pool)}{item.to_pool ? ` → ${poolName(item.to_pool)}` : ''}</p>
      {item.assigned_clan_tag && <p>Working placement removed: {item.assigned_clan_tag}</p>}
      <small>{new Date(item.created_at).toLocaleString()}</small>
      <DiscordContact userId={item.user_id} />
    </div>
    <button disabled={busy !== null} onClick={() => void review(item.id)}>{busy === item.id ? 'Saving…' : 'Mark reviewed'}</button>
  </article>
  if (!loading && !error && !items.length) return null
  return <section className="card signup-activity" aria-label="Member signup changes">
    <h2>Member signup changes{items.length ? ` · ${items.length}${items.length === 100 ? '+' : ''} to review` : ''}</h2>
    {loading && <p role="status">Checking withdrawals and pool changes…</p>}
    {error && <p role="alert">{error} <button onClick={() => setAttempt(value => value + 1)}>Retry alerts</button></p>}
    {items.length > 0 && <>
      <p>Review these changes before publishing again. Existing published rosters stay unchanged.</p>
      {items.slice(0, 3).map(row)}
      {items.length > 3 && <details><summary>Show {items.length - 3} more changes</summary>{items.slice(3).map(row)}</details>}
    </>}
  </section>
}
