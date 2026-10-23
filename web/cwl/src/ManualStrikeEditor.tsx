import { useEffect, useRef, useState } from 'react'
import { api } from './api'

type Account = { tag: string; name: string; current_clan_name?: string | null }
type Member = { id: string; name: string; accounts: Account[] }
type Props = {
  initialAccount?: { player_tag: string; player_name: string } | null
  onCancel: () => void
  onSaved: () => Promise<void>
  onDirty: (dirty: boolean) => void
  onBusy: (busy: boolean) => void
}
const message = (cause: unknown) =>
  cause instanceof Error ? cause.message : 'Could not load accounts. Try again.'

export default function ManualStrikeEditor({
  initialAccount,
  onCancel,
  onSaved,
  onDirty,
  onBusy,
}: Props) {
  const [mode, setMode] = useState<'member' | 'tag'>(
    initialAccount ? 'tag' : 'member',
  )
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<Member[]>([])
  const [member, setMember] = useState<Member | null>(null)
  const [tag, setTag] = useState(initialAccount?.player_tag || '')
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [review, setReview] = useState(false)
  const [retry, setRetry] = useState(0)
  const sequence = useRef(0)
  const submitting = useRef(false)
  const requestId = useRef(crypto.randomUUID())
  const heading = useRef<HTMLHeadingElement>(null)
  const account = member?.accounts.find((item) => item.tag === tag)
  const name =
    account?.name ||
    (tag === initialAccount?.player_tag ? initialAccount.player_name : tag)
  useEffect(() => {
    heading.current?.focus()
  }, [review])
  useEffect(() => {
    onDirty(!!(reason || query || tag || review))
    return () => onDirty(false)
  }, [reason, query, tag, review, onDirty])
  useEffect(() => {
    const turn = ++sequence.current
    if (mode !== 'member' || member || query.trim().length < 2) {
      setLoading(false)
      return
    }
    setMatches([])
    setLoading(true)
    setError('')
    const timer = setTimeout(() => {
      void api<{ members: Member[] }>(
        `/strikes/members?query=${encodeURIComponent(query.trim())}`,
      )
        .then((data) => {
          if (turn === sequence.current) setMatches(data.members)
        })
        .catch((cause) => {
          if (turn === sequence.current) setError(message(cause))
        })
        .finally(() => {
          if (turn === sequence.current) setLoading(false)
        })
    }, 250)
    return () => {
      clearTimeout(timer)
      sequence.current++
    }
  }, [query, mode, member, retry])
  async function choose(value: Member) {
    const turn = ++sequence.current
    setTag('')
    setMember(null)
    setMatches([])
    setLoading(true)
    setError('')
    try {
      const data = await api<{ member: Member }>(
        `/strikes/members/${encodeURIComponent(value.id)}/accounts`,
      )
      if (turn !== sequence.current) return
      setMember(data.member)
      // Require an explicit account choice, even for a member with one account.
    } catch (cause) {
      if (turn === sequence.current) setError(message(cause))
    } finally {
      if (turn === sequence.current) setLoading(false)
    }
  }
  async function save() {
    if (submitting.current || !review || !tag.trim() || !reason.trim()) return
    submitting.current = true
    setBusy(true)
    onBusy(true)
    setError('')
    try {
      await api('/strikes/manual', 'POST', {
        player_tag: tag.trim(),
        reason: reason.trim(),
        request_id: requestId.current,
      })
      onDirty(false)
      await onSaved()
    } catch (cause) {
      setError(message(cause))
    } finally {
      submitting.current = false
      setBusy(false)
      onBusy(false)
    }
  }
  return (
    <section
      className="card strikes-form"
      aria-label="Add strike"
      aria-busy={busy}
    >
      <h2 ref={heading} tabIndex={-1}>
        {review ? 'Review strike' : 'Add a strike'}
      </h2>
      {error && (
        <div className="notice error" role="alert">
          {error}
          {!review && (
            <button
              type="button"
              onClick={() => setRetry((value) => value + 1)}
            >
              Retry lookup
            </button>
          )}
        </div>
      )}
      {review ? (
        <>
          <dl className="strike-review">
            <div>
              <dt>Account</dt>
              <dd>
                {name}
                {name !== tag && <small>{tag}</small>}
              </dd>
            </div>
            {member && (
              <div>
                <dt>Discord member</dt>
                <dd>
                  {member.name}
                  <small>{member.id}</small>
                </dd>
              </div>
            )}
            <div>
              <dt>Reason</dt>
              <dd>{reason}</dd>
            </div>
          </dl>
          <p>This adds one manual strike to this account.</p>
          <div className="strikes-inline">
            <button disabled={busy} onClick={() => setReview(false)}>
              Back
            </button>
            <button
              className="primary"
              disabled={busy}
              onClick={() => void save()}
            >
              {busy ? 'Saving…' : 'Confirm strike'}
            </button>
          </div>
        </>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (tag.trim() && reason.trim() && !loading) setReview(true)
          }}
        >
          <fieldset disabled={busy}>
            <label>
              Find account by
              <select
                value={mode}
                onChange={(event) => {
                  sequence.current++
                  setMode(event.target.value as 'member' | 'tag')
                  setMember(null)
                  setTag('')
                  setMatches([])
                  setError('')
                }}
              >
                <option value="member">Discord member</option>
                <option value="tag">Player tag</option>
              </select>
            </label>
            {mode === 'member' ? (
              <>
                <label>
                  Find Discord member
                  <input
                    type="search"
                    value={query}
                    onChange={(event) => {
                      sequence.current++
                      setQuery(event.target.value)
                      setMember(null)
                      setTag('')
                      setMatches([])
                    }}
                    placeholder="Name or Discord ID"
                  />
                </label>
                {loading && <p role="status">Looking up accounts…</p>}
                {!member && matches.length > 0 && (
                  <div className="strike-member-matches">
                    {matches.map((item) => (
                      <button
                        type="button"
                        key={item.id}
                        disabled={loading}
                        onClick={() => void choose(item)}
                      >
                        {item.name}
                        <small>{item.id}</small>
                      </button>
                    ))}
                  </div>
                )}
                {!member &&
                  !loading &&
                  !error &&
                  query.trim().length >= 2 &&
                  !matches.length && (
                    <p>
                      No matching members. Try another name or use a player tag.
                    </p>
                  )}
                {member && (
                  <>
                    <p>
                      {member.name} <small>· {member.id}</small>
                    </p>
                    <label>
                      Clash account
                      <select
                        required
                        value={tag}
                        onChange={(event) => setTag(event.target.value)}
                      >
                        <option value="">Choose an account</option>
                        {member.accounts.map((item) => (
                          <option key={item.tag} value={item.tag}>
                            {item.name} · {item.tag}
                          </option>
                        ))}
                      </select>
                    </label>
                    {!member.accounts.length && (
                      <p>No linked accounts found. You can use a player tag.</p>
                    )}
                  </>
                )}
              </>
            ) : (
              <label>
                Player tag
                <input
                  required
                  value={tag}
                  onChange={(event) => setTag(event.target.value)}
                  placeholder="#PLAYERTAG"
                />
              </label>
            )}
            <label>
              Reason
              <input
                required
                maxLength={300}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Why is this strike needed?"
              />
            </label>
          </fieldset>
          <div className="strikes-inline">
            <button type="button" disabled={busy} onClick={onCancel}>
              Cancel
            </button>
            <button
              className="primary"
              disabled={busy || loading || !tag.trim() || !reason.trim()}
            >
              Review strike
            </button>
          </div>
        </form>
      )}
    </section>
  )
}
