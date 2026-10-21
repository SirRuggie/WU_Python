import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type Season } from './api'
import CwlPoolTabs, { useCwlPool } from './CwlPoolTabs'
import useUnsavedWork from './useUnsavedWork'
import BonusAnnouncement from './BonusAnnouncement'
import { attacksText, type RaffleAccount, type RaffleData, type RafflePreview } from './bonusRaffle'
import './BonusWorkspace.css'

type Props = { seasonId: string; seasons: Season[]; onDirty?: (dirty: boolean) => void; onSeasonChange: (id: string) => void }

function AccountList({ accounts }: { accounts: RaffleAccount[] }) {
  return <ul className="bonus-account-list">{accounts.map(account => <li key={account.tag}>
    <div><strong>{account.player_name}</strong><small>{account.tag}</small></div>
    <div><span>{attacksText(account)}</span>{account.exclusion && <small>{account.exclusion}</small>}</div>
  </li>)}</ul>
}

export default function BonusWorkspace({ seasonId, seasons, onDirty, onSeasonChange }: Props) {
  const [pool, setPool] = useCwlPool()
  const [data, setData] = useState<RaffleData | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [clanTag, setClanTag] = useState('')
  const [minimum, setMinimum] = useState('')
  const [slots, setSlots] = useState('')
  const [cancelReason, setCancelReason] = useState('')
  const [preview, setPreview] = useState<RafflePreview | null>(null)
  const generation = useRef(0)
  const working = useRef(false)
  const activeSeason = useRef(seasonId)
  activeSeason.current = seasonId
  const path = `/seasons/${encodeURIComponent(seasonId)}/bonus-raffle`
  const dirty = !!data && minimum !== String(data.policies[pool] ?? '')
  useUnsavedWork(dirty || busy || !!cancelReason, onDirty)
  const archived = data?.season_status !== 'draft'
  const currentClans = data?.clans.filter(clan => data.accounts.some(a => a.pool === pool && a.assigned_clan_tag === clan.tag)) || []
  const clans = [...currentClans]
  for (const saved of data?.draws || []) {
    if (saved.pool === pool && saved.cycle === data?.cycle && !saved.cancelled_at && !clans.some(c => c.tag === saved.clan_tag)) {
      clans.push({ tag: saved.clan_tag, name: `${saved.snapshot.clan_name} · Saved draw`, slots: saved.snapshot.slots })
    }
  }
  const selectedClan = clans.find(c => c.tag === clanTag)
  const draw = data?.draws.find(d => d.pool === pool && d.clan_tag === clanTag && d.cycle === data.cycle && !d.cancelled_at)
  const changedContext = () => { setPreview(null); setSlots(''); setCancelReason(''); setNotice('') }

  const load = useCallback(async () => {
    if (!seasonId || working.current) return
    working.current = true
    const request = ++generation.current
    setBusy(true); setError('')
    try {
      const result = await api<RaffleData>(path)
      if (request !== generation.current) return
      setData(result)
      setPreview(null)
    } catch (cause) {
      if (request !== generation.current) return
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) setData(null)
      setError(cause instanceof Error ? cause.message : 'Could not load bonuses')
    } finally {
      if (request === generation.current) { working.current = false; setBusy(false) }
    }
  }, [path, seasonId])

  useEffect(() => {
    generation.current += 1; working.current = false
    setData(null); setClanTag(''); setPreview(null); setSlots(''); setCancelReason(''); setNotice(''); setError('')
    void load()
    return () => { generation.current += 1 }
  }, [load])
  useEffect(() => { if (data) setMinimum(String(data.policies[pool] ?? '')) }, [data, pool])
  useEffect(() => {
    if (!clans.some(c => c.tag === clanTag)) setClanTag(clans[0]?.tag || '')
  }, [data, pool, clanTag])

  const mutate = async (suffix: string, body: unknown, success: string, method = 'POST') => {
    if (working.current || archived) return
    working.current = true; setBusy(true); setError(''); setNotice('')
    const request = ++generation.current
    const sid = seasonId
    try {
      const result = await api<RaffleData>(path + suffix, method, body)
      if (request !== generation.current || activeSeason.current !== sid) return
      setData(result); setPreview(null); setCancelReason(''); setNotice(success)
    } catch (cause) {
      if (request !== generation.current) return
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) setData(null)
      setError(cause instanceof Error ? cause.message : 'The action could not be completed. Refresh to check its saved status.')
    } finally {
      if (request === generation.current) { working.current = false; setBusy(false) }
    }
  }
  const refresh = () => {
    if ((dirty || cancelReason) && !window.confirm('Discard unsaved bonus edits and refresh?')) return
    void load()
  }
  const review = async () => {
    if (working.current || !selectedClan || dirty || archived) return
    working.current = true; setBusy(true); setError(''); setPreview(null)
    const request = ++generation.current
    try {
      const result = await api<RafflePreview>(path + '/preview', 'POST', { pool, clan_tag: clanTag, slots: Number(slots) })
      if (request === generation.current) setPreview(result)
    } catch (cause) {
      if (request === generation.current) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) setData(null)
        setError(cause instanceof Error ? cause.message : 'Could not review accounts')
      }
    } finally {
      if (request === generation.current) { working.current = false; setBusy(false) }
    }
  }
  const stage = draw?.approved_at ? 3 : draw ? 2 : preview ? 1 : 0
  return <div className="bonus-workspace">
    <div className="page-head"><div><p className="eyebrow">CWL · Results &amp; bonuses</p><h1>Bonus winners</h1>
      <p>Review attacks, draw winners, then announce them to your clan.</p></div>
      <label className="season-choice">Season<select value={seasonId} disabled={busy} onChange={event => {
        if ((!dirty && !cancelReason) || window.confirm('Discard unsaved bonus edits and change season?')) onSeasonChange(event.target.value)
      }}><option value="">Select a season</option>{seasons.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}</select></label></div>
    <CwlPoolTabs value={pool} disabled={busy} onChange={next => {
      if ((!dirty && !cancelReason) || window.confirm('Discard unsaved bonus edits and switch CWL?')) { setPool(next); changedContext() }
    }} />
    {error && <div className="notice error" role="alert">{error} <button disabled={busy} onClick={refresh}>Refresh saved status</button></div>}
    {notice && <p role="status">{notice}</p>}
    {busy && <p role="status">Working…</p>}
    {!seasonId && <p>Select a season to begin.</p>}
    {data && <>
      <div className="bonus-toolbar"><strong>{pool === 'main' ? 'Main CWL' : 'Lazy CWL'} · {data.cycle || 'CWL month not set'}</strong>
        <button disabled={busy} onClick={refresh}>Refresh saved status</button></div>
      {archived && <p className="notice">Archived season · Read only</p>}
      {!data.cycle && <p className="notice">Choose this season’s CWL month in Results &amp; participation first.</p>}
      <div className="bonus-source"><strong>Account list: Current signups &amp; working assignments</strong>
        <p className="small">New draws include only accounts signed up for this season. Attacks come from Clash CWL results for {data.cycle || 'the selected month'}. Publishing is not required for bonus review.</p>
        <p className="small">Automatic checks: {data.sync.enabled ? 'On · every 15 minutes' : 'Off'} · Last check: {data.sync.last_checked_at ? new Date(data.sync.last_checked_at).toLocaleString() : 'Not checked yet'}</p>
        {data.sync.warning && <p role="status">{data.sync.warning}</p>}
        {data.historical_accounts_count > 0 && <p className="small">{data.historical_accounts_count} account{data.historical_accounts_count === 1 ? '' : 's'} from older rosters or saved results excluded from new draws.</p>}
        <button disabled={busy || archived || dirty || !data.cycle} onClick={() => void mutate('/refresh-results', {}, 'Clash results refreshed. Review any incomplete results before drawing.')}>Refresh attacks from Clash</button>
      </div>
      <ol className="bonus-steps" aria-label="Bonus progress">{['Review results', 'Draw winners', 'Approve winners', 'Announce'].map((step, index) =>
        <li key={step} aria-current={stage === index ? 'step' : undefined}><span>{index + 1}</span>{step}</li>)}</ol>
      <div className="bonus-setup">
        <label>Hosting clan<select value={clanTag} disabled={busy} onChange={event => { setClanTag(event.target.value); changedContext() }}>
          {!clans.length && <option value="">No assigned hosting clans</option>}{clans.map(c => <option key={c.tag} value={c.tag}>{c.name} · {c.tag}</option>)}</select></label>
        <div><label>Minimum attacks · {pool === 'main' ? 'Main CWL' : 'Lazy CWL'}<input type="number" min="0" max="7" step="1" value={minimum}
          disabled={busy || archived} onChange={event => { setMinimum(event.target.value); setPreview(null) }} placeholder="Choose minimum" /></label>
          <button disabled={busy || archived || !dirty || !/^\d+$/.test(minimum) || Number(minimum) > 7}
            onClick={() => void mutate('/policy', { pool, minimum: Number(minimum), revision: data.revision }, 'Minimum attacks saved. Existing draws stay unchanged.', 'PATCH')}>Save minimum</button></div>
      </div>
      {!clans.length && <p>No current signups are assigned to a hosting clan in this CWL pool. Check current signups and working assignments.</p>}
      {selectedClan && !draw && <section className="bonus-panel">
        <h2>{selectedClan.name}</h2><p>Each qualifying account gets one equal chance. Winners are saved and cannot be redrawn by refreshing.</p>
        <label className="bonus-slots">Total bonuses available for this clan<input type="number" min="1" max="50" step="1" value={slots}
          disabled={busy || archived} onChange={event => { setSlots(event.target.value); setPreview(null) }} placeholder="Count shown in-game" /></label>
        <p className="small">Enter the total count shown in Clash for this CWL season. Already saved selections are deducted. The game’s bonus allowance is not verified automatically.</p>
        <div className="bonus-action-bar"><span>{dirty ? 'Save the minimum attacks first.' : 'Review the results before drawing.'}</span>
          <button className="primary" disabled={busy || archived || dirty || !/^\d+$/.test(slots) || Number(slots) < 1 || Number(slots) > 50 || data.policies[pool] === null}
            onClick={() => void review()}>Review qualifying accounts</button></div>
        {preview && <section className="bonus-preview">
          <h3>{preview.eligible.length} accounts qualify · {Math.min(preview.available, preview.eligible.length)} winners</h3>
          <p>Minimum {preview.minimum} attacks · {preview.available} bonus slots remaining</p>
          {preview.available > preview.eligible.length && <p>There are fewer qualifying accounts than slots. Every qualifying account will win; remaining slots stay unused.</p>}
          {preview.blocking_reasons.length > 0 && <div className="notice error" role="alert">{preview.blocking_reasons.map(reason => <p key={reason}>{reason}</p>)}<p>Use Results &amp; participation to refresh or reconcile the results.</p></div>}
          <AccountList accounts={preview.eligible} />
          <details><summary>Accounts not included ({preview.excluded.length})</summary><AccountList accounts={preview.excluded} /></details>
          <div className="bonus-action-bar"><span>One saved draw per clan and CWL pool this month</span><button className="primary"
            disabled={busy || archived || !!preview.blocking_reasons.length} onClick={() => void mutate('/draw', { pool, clan_tag: clanTag, slots: Number(slots), fingerprint: preview.fingerprint }, 'Winners drawn and saved. Review them before approving.')}>Draw and save winners</button></div>
        </section>}
      </section>}
      {draw && <section className="bonus-panel">
        <div className="bonus-toolbar"><h2>{draw.snapshot.clan_name} · Bonus winners</h2><strong>{draw.approved_at ? 'Approved' : 'Awaiting staff review'}</strong></div>
        <p className="small">Saved draw · {new Date(draw.created_at).toLocaleString()}. These winners are preserved from the reviewed account list.</p>
        <p>{draw.snapshot.winners.length} winners · {draw.snapshot.eligible.length} qualifying accounts · Minimum {draw.snapshot.minimum} attacks</p>
        <AccountList accounts={draw.snapshot.winners} />
        <details><summary>Draw details and qualifying accounts</summary><p>Drawn {new Date(draw.created_at).toLocaleString()}. Saved results are preserved even if rules change later.</p><AccountList accounts={draw.snapshot.eligible} /></details>
        {!draw.approved_at && <div className="bonus-action-bar"><span>Approval records these winners. It does not send a message.</span><button className="primary" disabled={busy || archived || dirty}
          onClick={() => void mutate(`/${draw.id}/approve`, {}, 'Winners approved. Review the announcement and choose a channel.')}>Approve winners</button></div>}
        {!draw.approved_at && <details><summary>Correct a draw problem</summary><p>Cancel only when results or setup need correction. The original winners and reason stay in history.</p>
          <label>Reason<textarea maxLength={500} value={cancelReason} disabled={busy || archived} onChange={event => setCancelReason(event.target.value)} /></label>
          <button disabled={busy || archived || !cancelReason.trim()} onClick={() => void mutate(`/${draw.id}/cancel`, { reason: cancelReason.trim() }, 'Draw cancelled and retained in history. Correct the results before drawing again.')}>Cancel this draw</button></details>}
        {draw.approved_at && <BonusAnnouncement key={draw.id} draw={draw} disabled={busy || archived}
          onSend={(channel, retry = false) => void mutate(`/${draw.id}/send`, { channel_id: channel, retry }, 'Delivery status updated below.')} />}
      </section>}
      <details className="bonus-history"><summary>Saved bonus history ({data.history.length})</summary>
        <p className="small">Dashboard selections only. This is not proof that medals were awarded in-game.</p>
        {data.draws.filter(d => d.cancelled_at).map(d => <div className="bonus-history-row" key={`cancelled-${d.id}`}><strong>{d.snapshot.clan_name} · Cancelled draw</strong><p>{d.cancel_reason}</p><small>{new Date(d.cancelled_at!).toLocaleString()}</small><AccountList accounts={d.snapshot.winners} /></div>)}
        {data.history.map(item => <div className="bonus-history-row" key={item.id}><strong>{item.player_name} · {item.clan_name || item.clan_tag}</strong><small>{item.tag} · {item.cycle} · {item.voided_at ? 'Voided' : 'Approved'} · {new Date(item.confirmed_at).toLocaleString()}</small></div>)}
      </details>
    </>}
  </div>
}
