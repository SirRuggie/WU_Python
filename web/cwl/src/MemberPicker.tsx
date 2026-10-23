import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { ManagementOption, ManagementValue } from './serverManagement'
import './MemberPicker.css'
export type MemberOption = ManagementOption & {
  id: string
  display_name: string
  username: string
  avatar_url?: string | null
  role_ids: string[]
  role_names?: string[]
}
type MemberPage = {
  options: MemberOption[]
  next: string | null
  truncated: boolean
}
export function mergeMembers(old: MemberOption[], incoming: MemberOption[]) {
  return [
    ...new Map(
      [...old, ...incoming].map((member) => [member.value, member]),
    ).values(),
  ]
}
function Avatar({ member }: { member: MemberOption }) {
  const [failed, setFailed] = useState(false)
  return !failed &&
    member.avatar_url?.startsWith('https://cdn.discordapp.com/') ? (
    <img
      src={member.avatar_url}
      alt=""
      width={32}
      height={32}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  ) : (
    <span className="member-avatar" aria-hidden="true">
      {(member.display_name || member.label || '?').slice(0, 1)}
    </span>
  )
}
export default function MemberPicker({
  label,
  value,
  onChange,
  disabled,
  multiple = false,
  onOptions,
  roles = [],
  endpoint = '/manage/members',
  showRoles = true,
  compactSelection = false,
}: {
  label: string
  value: ManagementValue
  onChange: (value: ManagementValue) => void
  disabled: boolean
  multiple?: boolean
  onOptions?: (members: MemberOption[]) => void
  roles?: ManagementOption[]
  endpoint?: string
  showRoles?: boolean
  compactSelection?: boolean
}) {
  const [search, setSearch] = useState(''),
    [rows, setRows] = useState<MemberOption[]>([]),
    [known, setKnown] = useState<MemberOption[]>([]),
    [next, setNext] = useState<string | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(''),
    [truncated, setTruncated] = useState(false),
    [reload, setReload] = useState(0)
  const [changing, setChanging] = useState(false)
  const sequence = useRef(0),
    callback = useRef(onOptions)
  callback.current = onOptions
  const selected = Array.isArray(value) ? value : value ? [String(value)] : []
  useEffect(() => {
    const turn = ++sequence.current
    setLoading(true)
    setError('')
    setNext(null)
    setRows([])
    const timer = window.setTimeout(
      () => {
        api<MemberPage>(
          endpoint +
            (search.trim() ? '?q=' + encodeURIComponent(search.trim()) : ''),
        )
          .then((result) => {
            if (turn !== sequence.current) return
            setRows(result.options)
            setKnown((old) => mergeMembers(old, result.options))
            setNext(result.next)
            setTruncated(result.truncated)
            callback.current?.(result.options)
          })
          .catch((error) => {
            if (turn === sequence.current)
              setError(
                error instanceof Error
                  ? error.message
                  : 'Could not load members.',
              )
          })
          .finally(() => {
            if (turn === sequence.current) setLoading(false)
          })
      },
      search.trim() ? 300 : 0,
    )
    return () => {
      ++sequence.current
      window.clearTimeout(timer)
    }
  }, [search, reload, endpoint])
  async function more() {
    if (!next || loading) return
    const turn = sequence.current
    setLoading(true)
    setError('')
    try {
      const result = await api<MemberPage>(
        endpoint + '?after=' + encodeURIComponent(next),
      )
      if (turn !== sequence.current) return
      setRows((old) => mergeMembers(old, result.options))
      setKnown((old) => mergeMembers(old, result.options))
      setNext(result.next)
      callback.current?.(result.options)
    } catch (error) {
      if (turn === sequence.current)
        setError(
          error instanceof Error ? error.message : 'Could not load members.',
        )
    } finally {
      if (turn === sequence.current) setLoading(false)
    }
  }
  const selectionKey = JSON.stringify(selected)
  useEffect(() => {
    let alive = true
    const missing = selected.filter(
      (id) => !known.some((member) => member.value === id),
    )
    if (!missing.length) return
    Promise.all(
      missing
        .slice(0, 25)
        .map((id) =>
          api<MemberPage>(endpoint + '?id=' + encodeURIComponent(id)),
        ),
    )
      .then((pages) => {
        if (!alive) return
        const members = pages.flatMap((page) => page.options)
        setKnown((old) => mergeMembers(old, members))
        callback.current?.(members)
      })
      .catch(() => {
        if (alive) setError('Could not load the selected member. Search again.')
      })
    return () => {
      alive = false
    }
  }, [selectionKey, endpoint, reload])
  const picked = known.filter((member) => selected.includes(member.value))
  return (
    <section className="member-picker" aria-label={label}>
      <div
        hidden={
          compactSelection && !multiple && selected.length > 0 && !changing
        }
      >
        <label className="member-search">
          Search members
          <input
            type="search"
            value={search}
            maxLength={80}
            placeholder="Name, username or Discord ID"
            onChange={(event) => setSearch(event.target.value)}
            disabled={disabled}
          />
        </label>
        {search && (
          <button
            type="button"
            className="member-clear"
            disabled={disabled}
            onClick={() => setSearch('')}
          >
            Show all members
          </button>
        )}
      </div>
      {picked.length > 0 && (
        <div className="member-selected">
          <strong>
            {multiple ? `${picked.length} selected` : 'Selected member'}
          </strong>
          {picked.map((member) => (
            <div key={member.value} className="member-selected-row">
              <Avatar member={member} />
              <div>
                <strong>{member.display_name}</strong>
                <small>@{member.username}</small>
                <small>Discord ID: {member.id}</small>
                {!multiple && showRoles && (
                  <small>
                    {member.role_ids.length
                      ? `Current roles: ${(member.role_names || member.role_ids.map((id) => roles.find((role) => role.value === id)?.label).filter(Boolean)).join(', ') || member.role_ids.length}`
                      : 'No roles'}
                  </small>
                )}
              </div>
              <button
                type="button"
                disabled={disabled}
                aria-label={`Clear ${member.display_name}`}
                onClick={() =>
                  onChange(
                    multiple
                      ? selected.filter((id) => id !== member.value)
                      : '',
                  )
                }
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      {compactSelection && selected.length > 0 && !picked.length && (
        <p role="status">Selected Discord ID: {selected.join(', ')}</p>
      )}
      {compactSelection && !multiple && selected.length > 0 && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => setChanging((old) => !old)}
        >
          {changing ? 'Keep selected member' : 'Change member'}
        </button>
      )}
      <div
        hidden={
          compactSelection && !multiple && selected.length > 0 && !changing
        }
      >
        <fieldset
          className="member-options"
          disabled={disabled}
          aria-busy={loading}
        >
          <legend>{multiple ? 'Select members' : 'Select a member'}</legend>
          {rows.map((member) => (
            <label
              key={member.value}
              className={selected.includes(member.value) ? 'selected' : ''}
            >
              <input
                type={multiple ? 'checkbox' : 'radio'}
                name={multiple ? undefined : 'member-' + label}
                checked={selected.includes(member.value)}
                onChange={(event) => {
                  onChange(
                    multiple
                      ? event.target.checked
                        ? [...selected, member.value]
                        : selected.filter((id) => id !== member.value)
                      : member.value,
                  )
                  if (!multiple) setChanging(false)
                }}
              />
              <Avatar member={member} />
              <span>
                <strong>{member.display_name || member.label}</strong>
                <small>@{member.username}</small>
              </span>
            </label>
          ))}
        </fieldset>
      </div>
      {error && (
        <div className="member-error" role="alert">
          <span>{error}</span>
          <button
            type="button"
            disabled={disabled || loading}
            onClick={() => setReload((count) => count + 1)}
          >
            Try again
          </button>
        </div>
      )}
      <div
        hidden={
          compactSelection && !multiple && selected.length > 0 && !changing
        }
      >
        <div className="member-list-footer">
          <span role="status">
            {loading
              ? 'Loading members…'
              : error
                ? ''
                : !rows.length
                  ? 'No members found.'
                  : `${rows.length} members shown`}
          </span>
          {next && !search.trim() && (
            <button
              type="button"
              disabled={disabled || loading}
              onClick={() => void more()}
            >
              Show more
            </button>
          )}
        </div>
        {truncated && !loading && (
          <small>Type more of the name to narrow the list.</small>
        )}
      </div>
    </section>
  )
}
