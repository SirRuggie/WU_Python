import ManualStrikeEditor from './ManualStrikeEditor'
import useUnsavedWork from './useUnsavedWork'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import { strikePermissions } from './strikePermissions'
import StrikeTrackingStatus from './StrikeTrackingStatus'
import {
  detailQuery,
  importEmptyText,
  isCwlRecord,
  strikeBadge,
  strikeLinkLabel,
  warMatchup,
  warSummary,
} from './strikeHistoryView'
import {
  isStrikeImportJob,
  StrikeImportFailed,
  waitForStrikeImport,
  type StrikeImportJob,
} from './strikeImportJobs'
import {
  defaultLeaveTags,
  selectedImportEntries,
  toggleLeaveTag,
} from './strikeSelections'
import './StrikesWorkspace.css'

type Tab = 'history' | 'leave' | 'settings'
type Clan = { tag: string; name: string; is_fwa?: boolean }
type Account = { tag: string; name: string; current_clan_name?: string | null }
type Member = { id: string; name: string; accounts: Account[] }
type Entry = {
  id: string
  war_key?: string | null
  opponent_name?: string | null
  player_tag: string
  player_name: string
  discord_id?: string | null
  discord_name?: string | null
  link_status?: string | null
  current_clan_name?: string | null
  current_clan_tag?: string | null
  war_clan_name?: string | null
  war_clan_tag?: string | null
  war_end?: string | null
  kind: 'strike' | 'miss' | 'completed' | 'cwl'
  source: 'war' | 'manual' | 'cwl'
  source_label?: string | null
  war_type?: 'regular' | 'cwl'
  attacks_used?: number | null
  attacks_per_member?: number | null
  missed_attacks?: number | null
  status: 'active' | 'expired' | 'removed' | 'exempt' | 'recorded' | 'completed'
  reason?: string | null
  removed_reason?: string | null
}
type Overview = { entries: Entry[]; clans: Clan[]; total: number }
type StrikeAccount = {
  player_tag: string
  player_name: string
  discord_id?: string | null
  link_status?: string | null
  current_clan_tag?: string | null
  current_clan_name?: string | null
  clan_is_current?: boolean
  active_strikes: number
  total_strikes: number
  last_strike_at?: string | null
}
type AccountOverview = {
  accounts: StrikeAccount[]
  total: number
  clans: Clan[]
}
type War = {
  war_key: string
  clan_tag: string
  clan_name: string
  opponent_tag?: string
  opponent_name: string
  war_end: string
  missed_accounts: number
  strikes: number
  one_missed: number
  war_type?: 'regular' | 'cwl'
  cwl_missed?: number
  source_label?: string | null
  incomplete?: boolean
  review_message?: string | null
}
type Settings = {
  excluded_roles: { id: string; name: string }[]
  roles: { id: string; name: string }[]
  leaves: {
    discord_id: string
    display_name: string
    player_tags: string[]
    resume_date: string
  }[]
}
type ImportEntry = {
  key: string
  player_tag: string
  player_name: string
  clan_name: string
  war_end: string
  missed_attacks: number
  will_strike: boolean
  kind?: string
  source?: string
  war_type?: 'regular' | 'cwl'
  attacks_used?: number | null
  attacks_per_member?: number | null
  discord_id?: string | null
  link_status?: string | null
  exempt?: boolean
  duplicate?: boolean
}
type DeferredAccount = {
  player_tag: string
  player_name: string
  clan_name: string
  war_end?: string | null
  missed_attacks?: number
  reason?: string
  link_status?: string | null
}
type ImportResult = {
  applied: number
  strikes: number
  skipped: number | unknown[]
  cwl_wars?: number
  cwl_records?: number
  cwl_missed?: number
  deferred_count?: number
  deferred_accounts?: DeferredAccount[]
}
type ActiveImportJob = { job_id: string; phase: 'preview' | 'apply' }
type ImportDraft = {
  job: ActiveImportJob | null
  preview: ImportPreview | null
  excluded: string[]
}
type ImportPreview = {
  preview_id: string
  wars_scanned: number
  complete_wars: number
  incomplete_wars: number
  cwl_wars?: number
  cwl_records?: number
  cwl_missed?: number
  entries: ImportEntry[]
  deferred_accounts?: DeferredAccount[]
  deferred_count?: number
  coverage: {
    clan_name: string
    earliest?: string
    latest?: string
    wars: number
    error?: string
    skipped?: number
    processing_skipped_wars?: number
    deferred_accounts?: number
  }[]
}

const tabs: { id: Tab; label: string }[] = [
  { id: 'history', label: 'Accounts' },
  { id: 'leave', label: 'Leave' },
  { id: 'settings', label: 'Settings' },
]
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : 'Could not load data. Try again.'
const dateText = (value?: string | null) =>
  value
    ? /^\d{4}-\d{2}-\d{2}$/.test(value)
      ? new Date(`${value}T00:00:00`).toLocaleDateString()
      : new Date(value).toLocaleDateString()
    : '—'
const memberLabel = (member: Member) => `${member.name} · ${member.id}`
const importStorageKey = (userId: string) => `wu:strikes:import:${userId}`
function savedImport(userId: string): ImportDraft {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(importStorageKey(userId)) || '{}',
    )
    return {
      job:
        value.job &&
        typeof value.job.job_id === 'string' &&
        ['preview', 'apply'].includes(value.job.phase)
          ? value.job
          : null,
      preview:
        value.preview &&
        typeof value.preview.preview_id === 'string' &&
        Array.isArray(value.preview.entries)
          ? value.preview
          : null,
      excluded: Array.isArray(value.excluded)
        ? value.excluded.filter((key: unknown) => typeof key === 'string')
        : [],
    }
  } catch {
    return { job: null, preview: null, excluded: [] }
  }
}
const importResultText = (result: ImportResult) =>
  `${result.applied} records saved · ${result.strikes} strikes · ${Array.isArray(result.skipped) ? result.skipped.length : result.skipped} records skipped${result.cwl_records ? ` · ${result.cwl_records} CWL records` : ''}${(result.deferred_count ?? result.deferred_accounts?.length ?? 0) > 0 ? ` · ${result.deferred_count ?? result.deferred_accounts?.length} need review` : ''}.`

export default function StrikesWorkspace({
  permissions,
  isOwner,
  userId,
  onDirty,
}: {
  permissions: string[]
  isOwner: boolean
  userId: string
  onDirty?: (dirty: boolean) => void
}) {
  const access = strikePermissions(permissions, isOwner)
  const visibleTabs = tabs.filter((item) =>
    item.id === 'leave'
      ? access.manage
      : item.id === 'settings'
        ? access.manage || access.add
        : true,
  )
  const initialImport = useRef<ImportDraft>(
    access.add
      ? savedImport(userId)
      : { job: null, preview: null, excluded: [] },
  )
  const [tab, setTab] = useState<Tab>(
    initialImport.current.job || initialImport.current.preview
      ? 'settings'
      : 'history',
  )
  const [importOpen, setImportOpen] = useState(
    !!(initialImport.current.job || initialImport.current.preview),
  )
  const [overview, setOverview] = useState<Overview>({
    entries: [],
    clans: [],
    total: 0,
  })
  const [accountOverview, setAccountOverview] = useState<AccountOverview>({
    accounts: [],
    clans: [],
    total: 0,
  })
  const [selectedAccount, setSelectedAccount] = useState<StrikeAccount | null>(
    null,
  )
  const [query, setQuery] = useState('')
  const [historyMember, setHistoryMember] = useState<Member | null>(null)
  const [historyMatches, setHistoryMatches] = useState<Member[]>([])
  const [status, setStatus] = useState('strikes')
  const [accountStatus, setAccountStatus] = useState<'active' | 'all'>('active')
  const [showWarSearch, setShowWarSearch] = useState(false)
  const [warQuery, setWarQuery] = useState('')
  const [wars, setWars] = useState<War[]>([])
  const [warLoading, setWarLoading] = useState(false)
  const [warError, setWarError] = useState('')
  const [selectedWar, setSelectedWar] = useState<War | null>(null)
  const [clan, setClan] = useState('')
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  const historyRequest = useRef(0)
  const accountRequest = useRef(0)
  const memberRequest = useRef(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [manualOpen, setManualOpen] = useState(false)
  const [memberQuery, setMemberQuery] = useState('')
  const [memberError, setMemberError] = useState('')
  const [endingLeave, setEndingLeave] = useState('')
  const [members, setMembers] = useState<Member[]>([])
  const [selectedMember, setSelectedMember] = useState('')
  const [manualDirty, setManualDirty] = useState(false)
  const mutation = useRef(false)
  const [removeId, setRemoveId] = useState('')
  const [removeReason, setRemoveReason] = useState('')
  const [settings, setSettings] = useState<Settings | null>(null)
  const [roleId, setRoleId] = useState('')
  const [resumeDate, setResumeDate] = useState('')
  const [leaveTags, setLeaveTags] = useState<string[]>([])
  const [preview, setPreview] = useState<ImportPreview | null>(
    initialImport.current.preview,
  )
  const [excluded, setExcluded] = useState<string[]>(
    initialImport.current.excluded,
  )
  const [importJob, setImportJob] = useState<ActiveImportJob | null>(
    initialImport.current.job,
  )
  const [jobRetryPaused, setJobRetryPaused] = useState(false)
  const [jobRetry, setJobRetry] = useState(0)

  const dirty =
    manualDirty || !!removeReason || !!resumeDate || leaveTags.length > 0
  useUnsavedWork(dirty || busy, onDirty)
  const leaveDraft = () =>
    !busy && (!dirty || window.confirm('Discard unsaved changes?'))

  const refreshHistory = useCallback(async () => {
    const request = ++historyRequest.current
    setLoading(true)
    setError('')
    try {
      const params = detailQuery(
        page,
        status,
        selectedAccount?.player_tag,
        selectedWar?.war_key,
      )
      const data = await api<Overview>(`/strikes/overview?${params}`)
      if (request === historyRequest.current) setOverview(data)
    } catch (err) {
      if (request === historyRequest.current) setError(errorText(err))
    } finally {
      if (request === historyRequest.current) setLoading(false)
    }
  }, [page, status, selectedWar?.war_key, selectedAccount?.player_tag])
  const refreshAccounts = useCallback(async () => {
    const request = ++accountRequest.current
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({
        limit: '25',
        offset: String(page * 25),
        status: accountStatus,
      })
      if (historyMember?.id || query.trim())
        params.set('query', historyMember?.id || query.trim())
      if (clan) params.set('clan', clan)
      const data = await api<AccountOverview>(`/strikes/accounts?${params}`)
      if (request === accountRequest.current) setAccountOverview(data)
    } catch (err) {
      if (request === accountRequest.current) setError(errorText(err))
    } finally {
      if (request === accountRequest.current) setLoading(false)
    }
  }, [page, query, historyMember?.id, clan, accountStatus])
  useEffect(() => {
    if (tab !== 'history') return
    const timer = setTimeout(
      () =>
        void (selectedAccount || selectedWar
          ? refreshHistory()
          : refreshAccounts()),
      180,
    )
    return () => {
      clearTimeout(timer)
      historyRequest.current++
      accountRequest.current++
    }
  }, [tab, selectedAccount, selectedWar, refreshHistory, refreshAccounts])
  useEffect(() => {
    if (!['history', 'leave'].includes(tab) || !memberQuery.trim()) {
      setMembers([])
      return
    }
    let active = true
    setMemberError('')
    const timer = setTimeout(() => {
      void api<{ members: Member[] }>(
        `/strikes/members?query=${encodeURIComponent(memberQuery.trim())}`,
      )
        .then((data) => {
          if (active) setMembers(data.members)
        })
        .catch((cause) => {
          if (active) {
            setMembers([])
            setMemberError(errorText(cause))
          }
        })
    }, 250)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [memberQuery, tab])
  useEffect(() => {
    setPage(0)
  }, [
    query,
    historyMember?.id,
    status,
    accountStatus,
    clan,
    selectedWar?.war_key,
    selectedAccount?.player_tag,
  ])
  useEffect(() => {
    if (tab !== 'history' || !showWarSearch) return
    let active = true
    const timer = setTimeout(() => {
      setWarLoading(true)
      setWarError('')
      const params = new URLSearchParams()
      if (warQuery.trim()) params.set('query', warQuery.trim())
      if (clan) params.set('clan', clan)
      void api<{ wars: War[] }>(`/strikes/wars?${params}`)
        .then((data) => {
          if (active) setWars(data.wars)
        })
        .catch((err) => {
          if (active) setWarError(errorText(err))
        })
        .finally(() => {
          if (active) setWarLoading(false)
        })
    }, 250)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [tab, showWarSearch, warQuery, clan])
  useEffect(() => {
    if (
      tab !== 'history' ||
      selectedAccount ||
      selectedWar ||
      historyMember ||
      query.trim().length < 2 ||
      query.trim().startsWith('#') ||
      /^\d+$/.test(query.trim())
    ) {
      setHistoryMatches([])
      return
    }
    let active = true
    const timer = setTimeout(() => {
      void api<{ members: Member[] }>(
        `/strikes/members?query=${encodeURIComponent(query.trim())}`,
      )
        .then((data) => {
          if (active) setHistoryMatches(data.members)
        })
        .catch(() => {
          if (active) setHistoryMatches([])
        })
    }, 250)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [query, historyMember, tab, selectedAccount, selectedWar])
  useEffect(() => {
    if (!access.manage || (tab !== 'settings' && tab !== 'leave')) return
    let active = true
    setSettings(null)
    void api<Settings>('/strikes/settings')
      .then((data) => {
        if (active) setSettings(data)
      })
      .catch((err) => {
        if (active) setError(errorText(err))
      })
    return () => {
      active = false
    }
  }, [tab, access.manage])
  const run = async (
    action: () => Promise<unknown>,
    success: string,
    after?: () => void | Promise<void>,
  ) => {
    if (mutation.current) return
    mutation.current = true
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await action()
      setNotice(success)
      await after?.()
    } catch (err) {
      setError(errorText(err))
    } finally {
      mutation.current = false
      setBusy(false)
    }
  }
  const chooseMember = async (id: string) => {
    const request = ++memberRequest.current
    setLeaveTags([])
    setSelectedMember(id)
    if (!id) {
      setLeaveTags([])
      return
    }
    let member: Member
    try {
      member = (
        await api<{ member: Member }>(
          `/strikes/members/${encodeURIComponent(id)}/accounts`,
        )
      ).member
    } catch (err) {
      if (request === memberRequest.current) setError(errorText(err))
      return
    }
    if (request !== memberRequest.current) return
    setMembers((current) =>
      current.map((item) => (item.id === id ? member : item)),
    )
    setLeaveTags(defaultLeaveTags(member?.accounts || []))
  }
  const clearWar = () => {
    setSelectedWar(null)
    setStatus('strikes')
    setWarQuery('')
  }
  const backToAccounts = () => {
    if (!leaveDraft()) return
    setRemoveId('')
    setRemoveReason('')
    setSelectedAccount(null)
    clearWar()
  }
  const chooseAccount = (account: StrikeAccount) => {
    setSelectedAccount(account)
    setSelectedWar(null)
    setStatus(account.total_strikes === 0 ? 'all' : 'strikes')
    setPage(0)
  }
  const chooseWar = (war: War) => {
    setSelectedAccount(null)
    setSelectedWar(war)
    setStatus('all')
    setQuery('')
    setHistoryMember(null)
    setShowWarSearch(false)
    setPage(0)
  }
  const refreshAfterChange = async () => {
    if (selectedAccount || selectedWar) await refreshHistory()
    else await refreshAccounts()
    if (selectedAccount) {
      const data = await api<AccountOverview>(
        `/strikes/accounts?query=${encodeURIComponent(selectedAccount.player_tag)}&status=all`,
      )
      const updated = data.accounts.find(
        (account) => account.player_tag === selectedAccount.player_tag,
      )
      if (updated) setSelectedAccount(updated)
    }
  }
  const selected = members.find((item) => item.id === selectedMember)
  const importSelected = selectedImportEntries(preview?.entries || [], excluded)
  const deferredAccounts = preview?.deferred_accounts || []
  const deferredCount = preview?.deferred_count ?? deferredAccounts.length
  const updateSettings = async () =>
    setSettings(await api<Settings>('/strikes/settings'))
  useEffect(() => {
    try {
      if (!preview && !importJob)
        sessionStorage.removeItem(importStorageKey(userId))
      else
        sessionStorage.setItem(
          importStorageKey(userId),
          JSON.stringify({ preview, excluded, job: importJob }),
        )
    } catch {
      /* Browser storage is optional; active page still works. */
    }
  }, [userId, preview, excluded, importJob])
  useEffect(() => {
    if (!importJob || jobRetryPaused) return
    const controller = new AbortController()
    void waitForStrikeImport<ImportPreview | ImportResult>(
      importJob.job_id,
      (id) =>
        api<StrikeImportJob<ImportPreview | ImportResult>>(
          `/strikes/import/jobs/${encodeURIComponent(id)}`,
        ),
      controller.signal,
    )
      .then((result) => {
        if (controller.signal.aborted) return
        if (importJob.phase === 'preview') {
          setPreview(result as ImportPreview)
          setExcluded([])
          setNotice('Preview ready.')
        } else {
          setPreview(null)
          setExcluded([])
          setNotice(importResultText(result as ImportResult))
          void refreshHistory()
        }
        setImportJob(null)
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        if (
          err instanceof StrikeImportFailed ||
          (err instanceof ApiError && err.status === 404)
        )
          setImportJob(null)
        else setJobRetryPaused(true)
        setError(errorText(err))
      })
    return () => controller.abort()
  }, [
    importJob?.job_id,
    importJob?.phase,
    refreshHistory,
    jobRetry,
    jobRetryPaused,
  ])
  const startImportPreview = async () => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await api<ImportPreview | StrikeImportJob<ImportPreview>>(
        '/strikes/import/preview',
        'POST',
        { days: 60 },
      )
      if (isStrikeImportJob(result)) {
        setJobRetryPaused(false)
        setImportJob({ job_id: result.job_id, phase: 'preview' })
      } else {
        setPreview(result as ImportPreview)
        setExcluded([])
        setNotice('Preview ready.')
      }
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  const startImportApply = async () => {
    if (!preview) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await api<ImportResult | StrikeImportJob<ImportResult>>(
        '/strikes/import/apply',
        'POST',
        { preview_id: preview.preview_id, excluded_keys: excluded },
      )
      if (isStrikeImportJob(result)) {
        setJobRetryPaused(false)
        setImportJob({ job_id: result.job_id, phase: 'apply' })
      } else {
        setPreview(null)
        setExcluded([])
        setNotice(importResultText(result as ImportResult))
        void refreshHistory()
      }
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="strikes-workspace">
      <div className="page-head">
        <div>
          <p className="eyebrow">Family clans</p>
          <h1>Strikes</h1>
          <p>Review active strikes, account history, and approved leave.</p>
        </div>
      </div>
      <div className="strikes-tabs" role="group" aria-label="Strike sections">
        {visibleTabs.map((item) => (
          <button
            key={item.id}
            aria-pressed={tab === item.id}
            disabled={busy}
            onClick={() => {
              if (!leaveDraft()) return
              setManualOpen(false)
              setManualDirty(false)
              memberRequest.current++
              setRemoveId('')
              setRemoveReason('')
              setLeaveTags([])
              setResumeDate('')
              setTab(item.id)
              setError('')
              setNotice('')
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
          {tab === 'history' && (
            <button
              disabled={busy}
              onClick={() =>
                void (selectedAccount || selectedWar
                  ? refreshHistory()
                  : refreshAccounts())
              }
            >
              Reload records
            </button>
          )}
        </div>
      )}
      {notice && (
        <div className="notice success" role="status">
          {notice}
        </div>
      )}

      {tab === 'history' && manualOpen && (
        <ManualStrikeEditor
          initialAccount={selectedAccount}
          onDirty={setManualDirty}
          onBusy={setBusy}
          onCancel={() => {
            if (leaveDraft()) {
              setManualOpen(false)
              setManualDirty(false)
              memberRequest.current++
            }
          }}
          onSaved={async () => {
            setManualOpen(false)
            setManualDirty(false)
            setNotice('Strike added.')
            await refreshAfterChange()
          }}
        />
      )}
      {tab === 'history' && !manualOpen && (
        <>
          <StrikeTrackingStatus canRetry={access.add} />
          <div className="strikes-toolbar">
            {!selectedAccount && !selectedWar && (
              <div className="strikes-history-search">
                <label>
                  Find player or member
                  <input
                    type="search"
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value)
                      setHistoryMember(null)
                    }}
                    placeholder="Name, tag or Discord ID"
                  />
                </label>
                {historyMember && (
                  <button
                    className="strikes-picked-member"
                    onClick={() => {
                      setHistoryMember(null)
                      setQuery('')
                    }}
                  >
                    Member: {historyMember.name} ×
                  </button>
                )}
                {historyMatches.length > 0 && (
                  <div
                    className="strikes-search-matches"
                    role="group"
                    aria-label="Matching Discord members"
                  >
                    {historyMatches.map((item) => (
                      <button
                        key={item.id}
                        onClick={() => {
                          setHistoryMember(item)
                          setQuery(item.name)
                          setHistoryMatches([])
                        }}
                      >
                        {item.name}
                        <small>{item.id}</small>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {selectedAccount && (
              <button onClick={backToAccounts}>← Players</button>
            )}
            {selectedAccount && (
              <label>
                Status
                <select
                  value={status}
                  disabled={!!selectedWar}
                  onChange={(event) => setStatus(event.target.value)}
                >
                  <option value="strikes">Strikes</option>
                  <option value="all">All records</option>
                  <option value="active">Active</option>
                  <option value="recorded">One missed</option>
                  <option value="cwl">CWL</option>
                  <option value="expired">Expired</option>
                  <option value="removed">Removed</option>
                  <option value="exempt">Exempt</option>
                </select>
              </label>
            )}
            {!selectedAccount && !selectedWar && (
              <label>
                Show
                <select
                  value={accountStatus}
                  onChange={(event) =>
                    setAccountStatus(event.target.value as 'active' | 'all')
                  }
                >
                  <option value="active">Active strikes</option>
                  <option value="all">All accounts</option>
                </select>
              </label>
            )}
            {!selectedAccount && !selectedWar && (
              <label>
                Clan
                <select
                  value={clan}
                  onChange={(event) => setClan(event.target.value)}
                >
                  <option value="">All clans</option>
                  {accountOverview.clans.map((item) => (
                    <option key={item.tag} value={item.tag}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {access.add && (
              <button
                className="primary"
                disabled={busy}
                onClick={() => {
                  if (leaveDraft()) {
                    setNotice('')
                    setError('')
                    setManualOpen(true)
                  }
                }}
              >
                {manualOpen ? 'Close' : 'Add strike'}
              </button>
            )}
          </div>
          <div className="strikes-war-tools">
            <button
              aria-expanded={showWarSearch}
              onClick={() => setShowWarSearch((open) => !open)}
            >
              {showWarSearch ? 'Close war search' : 'Find war'}
            </button>
            {selectedWar && (
              <div className="strikes-selected-war">
                <span>
                  {warMatchup(selectedWar.clan_name, selectedWar.opponent_name)}{' '}
                  · {dateText(selectedWar.war_end)} · {selectedWar.source_label || 'Source unavailable'}
                  {selectedWar.incomplete ? ' · Incomplete · No automatic strikes' : ' · All records'}
                </span>
                <button onClick={clearWar}>Clear war</button>
              </div>
            )}
          </div>
          {showWarSearch && (
            <div className="card strikes-war-search">
              <label>
                Find war
                <input
                  type="search"
                  value={warQuery}
                  onChange={(event) => setWarQuery(event.target.value)}
                  placeholder="Opponent, clan, or date"
                />
              </label>
              {warLoading ? (
                <p role="status">Finding wars…</p>
              ) : warError ? (
                <p role="alert">{warError}</p>
              ) : wars.length === 0 ? (
                <p>No saved wars found.</p>
              ) : (
                <div className="strikes-war-results">
                  {wars.map((war) => (
                    <button key={war.war_key} onClick={() => chooseWar(war)}>
                      <strong>
                        {warMatchup(war.clan_name, war.opponent_name)}
                      </strong>
                      <span>
                        {dateText(war.war_end)} · {war.source_label || 'Source unavailable'} ·{' '}
                        {war.incomplete
                          ? `${war.review_message || 'War ended before final check: review in Find war'} · No automatic strikes`
                          : warSummary(war)}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          {selectedAccount || selectedWar ? (
            <>
              {selectedAccount && (
                <div className="strikes-detail-context">
                  {selectedAccount.player_tag} ·{' '}
                  {selectedAccount.current_clan_name
                    ? `${selectedAccount.clan_is_current === false ? 'Last known' : 'Current'}: ${selectedAccount.current_clan_name}`
                    : 'No clan'}{' '}
                  · {selectedAccount.active_strikes} active strikes
                </div>
              )}
              <div className="strikes-list-head">
                <h2>
                  {selectedAccount
                    ? selectedAccount.player_name
                    : 'War history'}
                </h2>
                <span>
                  {loading ? 'Loading…' : `${overview.total} records`}
                </span>
              </div>
              {!loading && !error && overview.entries.length === 0 && (
                <div className="card strikes-empty">
                  {status === 'strikes'
                    ? 'No strikes found.'
                    : 'No records found.'}
                </div>
              )}
              <div className="strikes-list">
                {!loading &&
                  !error &&
                  overview.entries.map((item) => (
                    <article className="card strikes-record" key={item.id}>
                      <div className="strikes-record-main">
                        <div>
                          <strong>{item.player_name || item.player_tag}</strong>
                          <small>
                            {item.player_tag} ·{' '}
                            {strikeLinkLabel(
                              item.discord_id,
                              item.discord_name,
                              item.link_status,
                            )}
                          </small>
                        </div>
                        <span
                          className={`strikes-badge ${isCwlRecord(item) ? 'cwl' : item.status}`}
                        >
                          {strikeBadge(
                            item.kind,
                            item.status,
                            item.attacks_used,
                          )}
                        </span>
                      </div>
                      <div className="strikes-record-meta">
                        <span>
                          Current:{' '}
                          <strong>{item.current_clan_name || 'No clan'}</strong>
                        </span>
                        <span>
                          {item.source === 'manual' ? 'Added in: ' : 'War: '}
                          <strong>
                            {item.source === 'manual'
                              ? item.war_clan_name || 'Manual'
                              : warMatchup(
                                  item.war_clan_name,
                                  item.opponent_name,
                                )}
                          </strong>
                        </span>
                        <span>{dateText(item.war_end)}</span>
                        {item.source_label && <span>{item.source_label}</span>}
                        {isCwlRecord(item) && (
                          <span className="strikes-cwl-context">
                            CWL · No strikes
                          </span>
                        )}
                      </div>
                      {item.reason && (
                        <p className="strikes-reason">{item.reason}</p>
                      )}
                      {item.removed_reason && (
                        <p className="strikes-reason">
                          Removed: {item.removed_reason}
                        </p>
                      )}
                      {access.remove &&
                        item.kind === 'strike' &&
                        item.status === 'active' && (
                          <div className="strikes-record-actions">
                            {removeId !== item.id ? (
                              <button
                                onClick={() => {
                                  setRemoveId(item.id)
                                  setRemoveReason('')
                                }}
                              >
                                Remove strike
                              </button>
                            ) : (
                              <form
                                onSubmit={(event) => {
                                  event.preventDefault()
                                  if (!removeReason.trim()) return
                                  void run(
                                    () =>
                                      api(
                                        `/strikes/${encodeURIComponent(item.id)}/remove`,
                                        'POST',
                                        { reason: removeReason.trim() },
                                      ),
                                    'Strike removed.',
                                    async () => {
                                      setRemoveId('')
                                      setRemoveReason('')
                                      await refreshAfterChange()
                                    },
                                  )
                                }}
                              >
                                <label>
                                  Why remove?
                                  <input
                                    disabled={busy}
                                    value={removeReason}
                                    onChange={(event) =>
                                      setRemoveReason(event.target.value)
                                    }
                                    required
                                    maxLength={300}
                                  />
                                </label>
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() => {
                                    setRemoveId('')
                                    setRemoveReason('')
                                  }}
                                >
                                  Cancel
                                </button>
                                <button disabled={busy || !removeReason.trim()}>
                                  Confirm removal
                                </button>
                              </form>
                            )}
                          </div>
                        )}
                    </article>
                  ))}
              </div>
              {overview.total > 25 && (
                <div className="strikes-pages">
                  <button
                    disabled={page === 0 || loading}
                    onClick={() => setPage((value) => value - 1)}
                  >
                    Previous
                  </button>
                  <span>
                    {page * 25 + 1}–{Math.min((page + 1) * 25, overview.total)}{' '}
                    of {overview.total}
                  </span>
                  <button
                    disabled={(page + 1) * 25 >= overview.total || loading}
                    onClick={() => setPage((value) => value + 1)}
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          ) : (
            <>
              <div className="strikes-list-head">
                <h2>Players</h2>
                <span>
                  {loading ? 'Loading…' : `${accountOverview.total} accounts`}
                </span>
              </div>
              {!loading && !error && accountOverview.accounts.length === 0 && (
                <div className="card strikes-empty">
                  {query || clan
                    ? 'No accounts match these filters.'
                    : accountStatus === 'active'
                      ? 'No active strikes. Choose All accounts to review past records.'
                      : 'No account history yet.'}
                </div>
              )}
              <div className="strikes-account-list">
                {!loading &&
                  !error &&
                  accountOverview.accounts.map((account) => (
                    <button
                      className="card strikes-account-row"
                      key={account.player_tag}
                      onClick={() => chooseAccount(account)}
                    >
                      <span className="strikes-account-name">
                        <strong>
                          {account.player_name || account.player_tag}
                        </strong>
                        <small>
                          {account.player_tag} ·{' '}
                          {account.current_clan_name
                            ? `${account.clan_is_current === false ? 'Last known' : 'Current'}: ${account.current_clan_name}`
                            : 'No clan'}
                        </small>
                        {!account.discord_id && <small>Not linked</small>}
                      </span>
                      <span className="strikes-account-count">
                        <strong>{account.active_strikes}</strong> active{' '}
                        {account.active_strikes === 1 ? 'strike' : 'strikes'}
                      </span>
                      <span className="strikes-account-more">
                        {account.total_strikes
                          ? `${account.total_strikes} total · Last ${dateText(account.last_strike_at)}`
                          : 'Missed attacks only'}
                      </span>
                      <span aria-hidden="true">›</span>
                    </button>
                  ))}
              </div>
              {accountOverview.total > 25 && (
                <div className="strikes-pages">
                  <button
                    disabled={page === 0 || loading}
                    onClick={() => setPage((value) => value - 1)}
                  >
                    Previous
                  </button>
                  <span>
                    {page * 25 + 1}–
                    {Math.min((page + 1) * 25, accountOverview.total)} of{' '}
                    {accountOverview.total}
                  </span>
                  <button
                    disabled={
                      (page + 1) * 25 >= accountOverview.total || loading
                    }
                    onClick={() => setPage((value) => value + 1)}
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}

      {tab === 'leave' && access.manage && (
        <>
          <details className="card strikes-leave-editor">
            <summary>Approve leave</summary>
            <div className="strikes-form">
              <h2>Approve leave</h2>
              <label>
                Find Discord member
                <input
                  type="search"
                  disabled={busy}
                  value={memberQuery}
                  onChange={(event) => {
                    memberRequest.current++
                    setMemberQuery(event.target.value)
                    setSelectedMember('')
                    setLeaveTags([])
                  }}
                  placeholder="Name or Discord ID"
                />
              </label>
              {memberError && (
                <p className="notice error" role="alert">
                  {memberError} Try searching again.
                </p>
              )}
              {members.length > 0 && (
                <label>
                  Member
                  <select
                    disabled={busy}
                    value={selectedMember}
                    onChange={(event) => chooseMember(event.target.value)}
                  >
                    <option value="">Choose member</option>
                    {members.map((item) => (
                      <option key={item.id} value={item.id}>
                        {memberLabel(item)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {selected && (
                <div className="strikes-account-checks">
                  <span>Accounts on leave</span>
                  {selected.accounts.map((item) => (
                    <label key={item.tag}>
                      <input
                        type="checkbox"
                        disabled={busy}
                        checked={leaveTags.includes(item.tag)}
                        onChange={(event) =>
                          setLeaveTags((current) =>
                            toggleLeaveTag(
                              current,
                              item.tag,
                              event.target.checked,
                            ),
                          )
                        }
                      />
                      {item.name} · {item.tag}
                    </label>
                  ))}
                </div>
              )}
              <label>
                Resume on (UTC)
                <input
                  type="date"
                  disabled={busy}
                  value={resumeDate}
                  min={new Date().toISOString().slice(0, 10)}
                  onChange={(event) => setResumeDate(event.target.value)}
                />
              </label>
              <button
                className="primary"
                disabled={
                  busy || !selectedMember || !leaveTags.length || !resumeDate
                }
                onClick={() =>
                  void run(
                    () =>
                      api('/strikes/settings/leaves', 'POST', {
                        discord_id: selectedMember,
                        player_tags: leaveTags,
                        resume_date: resumeDate,
                      }),
                    'Leave saved.',
                    async () => {
                      await updateSettings()
                      setSelectedMember('')
                      setMemberQuery('')
                      setLeaveTags([])
                      setResumeDate('')
                    },
                  )
                }
              >
                Save leave
              </button>
            </div>
          </details>
          {!settings && !error && <p role="status">Loading approved leave…</p>}
          <div className="strikes-list-head">
            <h2>Approved leave</h2>
          </div>
          {settings && settings.leaves.length === 0 && (
            <div className="card strikes-empty">No approved leave.</div>
          )}
          {settings?.leaves.map((item) => (
            <div className="card strikes-leave" key={item.discord_id}>
              <div>
                <strong>{item.display_name}</strong>
                <small>{item.player_tags.join(' · ')}</small>
                <span>Resume on: {dateText(item.resume_date)} UTC</span>
              </div>
              {endingLeave !== item.discord_id ? (
                <button
                  disabled={busy}
                  onClick={() => setEndingLeave(item.discord_id)}
                >
                  End leave
                </button>
              ) : (
                <div className="strikes-inline">
                  <span>End leave for {item.display_name} now?</span>
                  <button disabled={busy} onClick={() => setEndingLeave('')}>
                    Cancel
                  </button>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () =>
                          api(
                            `/strikes/settings/leaves/${encodeURIComponent(item.discord_id)}`,
                            'DELETE',
                          ),
                        'Leave ended.',
                        async () => {
                          setEndingLeave('')
                          await updateSettings()
                        },
                      )
                    }
                  >
                    Confirm end leave
                  </button>
                </div>
              )}
            </div>
          ))}
        </>
      )}

      {tab === 'settings' && access.manage && (
        <div className="card strikes-form">
          <h2>Exempt roles</h2>
          <p>Members with these roles do not receive automatic war strikes.</p>
          <div className="strikes-role-list">
            {settings?.excluded_roles.map((item) => (
              <div key={item.id}>
                <span>
                  {item.name} <small>{item.id}</small>
                </span>
                <button
                  disabled={busy}
                  onClick={() =>
                    void run(
                      () =>
                        api('/strikes/settings/roles', 'PUT', {
                          role_ids: settings.excluded_roles
                            .filter((role) => role.id !== item.id)
                            .map((role) => role.id),
                        }),
                      'Role removed.',
                      updateSettings,
                    )
                  }
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
          <div className="strikes-inline">
            <label>
              Add role
              <select
                value={roleId}
                onChange={(event) => setRoleId(event.target.value)}
              >
                <option value="">Choose role</option>
                {settings?.roles
                  .filter(
                    (item) =>
                      !settings.excluded_roles.some(
                        (role) => role.id === item.id,
                      ),
                  )
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
              </select>
            </label>
            <button
              disabled={busy || !roleId || !settings}
              onClick={() =>
                void run(
                  () =>
                    api('/strikes/settings/roles', 'PUT', {
                      role_ids: [
                        ...settings!.excluded_roles.map((item) => item.id),
                        roleId,
                      ],
                    }),
                  'Role added.',
                  async () => {
                    setRoleId('')
                    await updateSettings()
                  },
                )
              }
            >
              Add role
            </button>
          </div>
        </div>
      )}

      {tab === 'settings' && access.add && (
        <details
          className="card strikes-import-settings"
          open={importOpen}
          onToggle={(event) => setImportOpen(event.currentTarget.open)}
        >
          <summary>
            Import past wars
            {importJob ? ' · In progress' : preview ? ' · Preview ready' : ''}
          </summary>
          <div className="strikes-import-content">
            <div className="strikes-form">
              <h2>Import recent wars</h2>
              <p>
                Check up to 60 days of wars. Regular war misses may add strikes;
                CWL is records only.
              </p>
              <button
                className="primary"
                disabled={busy || !!importJob}
                onClick={() => void startImportPreview()}
              >
                {busy || importJob?.phase === 'preview'
                  ? 'Checking wars…'
                  : preview
                    ? 'Check again'
                    : 'Check past wars'}
              </button>
            </div>
            {importJob && (
              <div className="strikes-job-status" role="status">
                <span>
                  {jobRetryPaused
                    ? 'Connection paused. Retry status.'
                    : importJob.phase === 'preview'
                      ? 'Checking wars… You can return later.'
                      : 'Importing records… You can return later.'}
                </span>
                {jobRetryPaused && (
                  <button
                    onClick={() => {
                      setJobRetryPaused(false)
                      setError('')
                      setJobRetry((value) => value + 1)
                    }}
                  >
                    Retry status
                  </button>
                )}
              </div>
            )}
            {preview && (
              <>
                <div className="strikes-import-counts">
                  <span>
                    <strong>{preview.complete_wars}</strong> complete wars
                  </span>
                  <span>
                    <strong>{preview.incomplete_wars}</strong> skipped wars
                  </span>
                  <span>
                    <strong>{deferredCount}</strong> need review
                  </span>
                  <span>
                    <strong>
                      {importSelected.filter((item) => item.will_strike).length}
                    </strong>{' '}
                    new strikes
                  </span>
                  <span>
                    <strong>
                      {
                        importSelected.filter(
                          (item) =>
                            !isCwlRecord(item) &&
                            !item.will_strike &&
                            !item.exempt,
                        ).length
                      }
                    </strong>{' '}
                    one missed
                  </span>
                  <span>
                    <strong>
                      {importSelected.filter((item) => item.exempt).length}
                    </strong>{' '}
                    exempt
                  </span>
                  <span>
                    <strong>{importSelected.filter(isCwlRecord).length}</strong>{' '}
                    CWL records
                  </span>
                </div>
                <details className="card strikes-coverage">
                  <summary>Coverage by clan</summary>
                  {preview.coverage.map((item) => (
                    <div key={item.clan_name}>
                      <strong>{item.clan_name}</strong>
                      <span>
                        {item.error
                          ? 'Unavailable'
                          : `${item.wars} wars${item.skipped || item.processing_skipped_wars ? ` · ${(item.skipped || 0) + (item.processing_skipped_wars || 0)} skipped wars` : ''}${item.deferred_accounts ? ` · ${item.deferred_accounts} need review` : ''} · ${dateText(item.earliest)} to ${dateText(item.latest)}`}
                      </span>
                    </div>
                  ))}
                </details>
                <div className="strikes-list-head">
                  <h2>Review incidents</h2>
                  <span>{preview.entries.length} found</span>
                </div>
                {preview.entries.length === 0 && (
                  <div className="card strikes-empty">
                    {importEmptyText(
                      preview.entries,
                      deferredCount,
                      preview.incomplete_wars,
                    )}
                  </div>
                )}
                <div className="strikes-list">
                  {preview.entries.map((item) => (
                    <div className="card strikes-import-row" key={item.key}>
                      <div>
                        <strong>{item.player_name}</strong>
                        <small>
                          {item.player_tag} · {item.clan_name} ·{' '}
                          {dateText(item.war_end)} ·{' '}
                          {strikeLinkLabel(
                            item.discord_id,
                            null,
                            item.link_status,
                          )}
                        </small>
                        <span>
                          {isCwlRecord(item)
                            ? `CWL · ${item.duplicate ? 'Already recorded' : item.attacks_used === 0 || item.missed_attacks > 0 ? 'Attack missed' : 'Attack used'} · No strikes`
                            : `${item.missed_attacks} missed · ${item.duplicate ? 'Already recorded' : item.exempt ? 'Exempt' : item.will_strike ? 'Strike' : 'Record only'}`}
                        </span>
                      </div>
                      {!item.duplicate && (
                        <label className="strikes-check">
                          <input
                            type="checkbox"
                            checked={!excluded.includes(item.key)}
                            disabled={importJob?.phase === 'apply'}
                            onChange={(event) =>
                              setExcluded((current) =>
                                event.target.checked
                                  ? current.filter((key) => key !== item.key)
                                  : [...current, item.key],
                              )
                            }
                          />
                          {isCwlRecord(item)
                            ? 'Save CWL record'
                            : item.exempt
                              ? 'Save exempt record'
                              : item.will_strike
                                ? 'Add strike'
                                : 'Save record'}
                        </label>
                      )}
                    </div>
                  ))}
                </div>
                {deferredCount > 0 && (
                  <details className="card strikes-needs-review">
                    <summary>Needs review ({deferredCount})</summary>
                    <div className="strikes-review-list">
                      {deferredAccounts.map((item, index) => (
                        <div
                          key={`${item.player_tag}-${item.war_end || index}`}
                        >
                          <strong>{item.player_name || item.player_tag}</strong>
                          <small>
                            {item.player_tag} · {item.clan_name}
                            {item.war_end ? ` · ${dateText(item.war_end)}` : ''}
                          </small>
                          <span>
                            {item.missed_attacks != null
                              ? `${item.missed_attacks} missed · `
                              : ''}
                            {item.reason || 'Account link needs review.'}
                          </span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
                <div className="strikes-import-apply">
                  <span>{importSelected.length} records selected</span>
                  <button
                    className="primary"
                    disabled={
                      busy || !!importJob || importSelected.length === 0
                    }
                    onClick={() => void startImportApply()}
                  >
                    {busy || importJob?.phase === 'apply'
                      ? 'Importing…'
                      : 'Import selected'}
                  </button>
                </div>
              </>
            )}
          </div>
        </details>
      )}
    </section>
  )
}
