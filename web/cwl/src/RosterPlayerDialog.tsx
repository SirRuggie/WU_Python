import ManualWeightFields from './ManualWeightFields'
import { manualWeightDraft, parseManualWeight } from './manualWeight'
import { useDashboardPermission } from './DashboardPermissions'
import useUnsavedWork from './useUnsavedWork'
import ClanDestinationOptions from './ClanDestinationOptions'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { RosterAccount, RosterClan } from './roster'
import type { Pool } from './api'
import RosterDiscordIdentity from './RosterDiscordIdentity'
import './RosterPlayerDialog.css'

type Props = {
  onDirty?: (dirty: boolean) => void
  account: RosterAccount
  clans: RosterClan[]
  busy: boolean
  error?: string
  onClose: () => void
  onSave: (body: Record<string, unknown>) => Promise<boolean>
  onRemove: () => Promise<boolean>
  onPoolChange?: (pool: Pool) => Promise<boolean>
  archived?: boolean
}

const fullWeight = (value: number | null) =>
  value === null ? 'Missing weight' : value.toLocaleString()

const sourceStatus = (status: RosterAccount['source_status']) =>
  status === 'current' ? 'Current' : status === 'unavailable'
    ? 'Source unavailable; prior value may be stale' : 'Missing weight'

export default function RosterPlayerDialog({
  account, clans, busy, error, onClose, onSave, onRemove, onPoolChange, onDirty, archived = false,
}: Props) {
  const canRoster = useDashboardPermission('cwl_roster')
  const canSignups = useDashboardPermission('cwl_signups')
  const ref = useRef<HTMLDialogElement>(null)
  const [weight, setWeight] = useState(manualWeightDraft(account.manual_weight))
  const [clan, setClan] = useState(account.assigned_clan_tag || '')
  const [kept, setKept] = useState(account.kept)
  const [localError, setLocalError] = useState('')
  const [poolReview, setPoolReview] = useState<Pool | null>(null)
  const currentHost = clans.find(item => item.tag === account.assigned_clan_tag)
  const dirty = JSON.stringify(weight) !== JSON.stringify(manualWeightDraft(account.manual_weight))
    || clan !== (account.assigned_clan_tag || '') || kept !== account.kept
  useUnsavedWork(dirty || busy || !!poolReview, onDirty)

  const close = () => {
    if (!busy && (!(dirty || poolReview) || window.confirm('Discard unsaved account changes?'))) onClose()
  }
  useEffect(() => {
    const dialog = ref.current
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
    dialog?.showModal()
    return () => {
      dialog?.close()
      requestAnimationFrame(() => {
        if (trigger?.isConnected && trigger.getClientRects().length && !trigger.closest('[inert]')) {
          trigger.focus({ preventScroll: true })
        }
      })
    }
  }, [])

  async function save() {
    if (!canRoster || archived) return
    try {
      const body: Record<string, unknown> = {}
      const value = account.clan_weight_managed ? account.manual_weight : parseManualWeight(weight)
      if (!account.clan_weight_managed && value !== account.manual_weight) body.manual_weight = value
      if (clan !== (account.assigned_clan_tag || '')) body.assigned_clan_tag = clan || null
      if (kept !== account.kept || clan !== (account.assigned_clan_tag || '')) body.kept = kept
      if (!Object.keys(body).length) { onClose(); return }
      setLocalError('')
      if (await onSave(body)) onClose()
    } catch (cause) {
      setLocalError(cause instanceof Error ? cause.message : 'Could not save changes.')
    }
  }

  async function remove() {
    if (!canSignups || archived) return
    if (!window.confirm(`Remove ${account.player_name} from this season's signups and working roster? Published rosters stay unchanged until you publish again.`)) return
    if (await onRemove()) onClose()
  }

  async function changePool() {
    if (!poolReview || !onPoolChange || !canSignups || archived || busy) return
    setLocalError('')
    if (await onPoolChange(poolReview)) onClose()
  }

  return createPortal(
    <dialog
      className="roster-player-dialog"
      ref={ref}
      onCancel={event => { event.preventDefault(); if (!busy) close() }}
      aria-labelledby="roster-player-title"
    >
      <header>
        <h2 id="roster-player-title">{account.player_name}</h2>
        <button type="button" disabled={busy} onClick={close}>Close ×</button>
      </header>
      <small>{account.tag} · TH {account.town_hall ?? '—'} · {account.pool === 'main' ? 'Main' : 'Lazy'} CWL</small>
      <RosterDiscordIdentity userId={account.user_id} />
      <dl className="roster-player-context">
        <div>
          <dt>Current clan</dt>
          <dd>{account.current_clan_status === 'unavailable' || !account.current_clan_status ? 'Unavailable' : account.current_clan_name || account.current_clan_tag || 'No clan'}{account.current_clan_status === 'stale' ? ' · Last checked' : ''}</dd>
        </div>
        <div>
          <dt>Weight used</dt>
          <dd>{fullWeight(account.effective_weight)}</dd>
        </div>
      </dl>
      <details className="roster-player-source">
        <summary>Weight source &amp; saved details</summary>
        <dl className="roster-player-context">
          <div><dt>Saved hosting clan</dt><dd>{currentHost?.name || account.assigned_clan_tag || 'Unassigned'}{currentHost?.archived ? ' · Archived' : ''}<small>{account.kept ? 'Kept placement' : 'Available for auto-placement'}</small></dd></div>
          <div><dt>Weight used</dt><dd>{fullWeight(account.effective_weight)}<small>{account.clan_weight_managed ? 'Using Clan weights' : account.manual_weight === null ? 'Using imported weight' : `Manual override: ${fullWeight(account.manual_weight)}`}</small>{account.initial_manual_weight != null && <small>First saved weight: {fullWeight(account.initial_manual_weight)}</small>}</dd></div>
          <div><dt>Source weight</dt><dd>{fullWeight(account.source_weight)}<small>{sourceStatus(account.source_status)}{account.source_name ? ` · ${account.source_name}` : ''}</small>{account.source_modified_at && <small>Source updated {new Date(account.source_modified_at).toLocaleString()}</small>}{account.source_checked_at && <small>Fetched {new Date(account.source_checked_at).toLocaleString()}</small>}</dd></div>
        </dl>
      </details>
      {canRoster && <form onSubmit={event => { event.preventDefault(); void save() }}>
        <fieldset disabled={busy || archived || !!poolReview}>
          {account.clan_weight_managed ? (
            <p>Weight from Clan weights: <strong>{fullWeight(account.effective_weight)}</strong>. Update it under Clan management → Clan weights.</p>
          ) : (
            <>
              <ManualWeightFields value={weight} onChange={setWeight} disabled={busy || !canRoster} />
              <small>Saved for future seasons. Leave blank to use source weight.</small>
            </>
          )}
          <label>Hosting clan
            <select value={clan} onChange={event => { setClan(event.target.value); setKept(true) }}>
              <option value="">Not assigned</option>
              {account.assigned_clan_tag && currentHost?.archived && <option value={account.assigned_clan_tag}>Archived clan · {account.assigned_clan_tag}</option>}
              <ClanDestinationOptions clans={clans} pool={account.pool} current={account.assigned_clan_tag} />
            </select>
          </label>
          <label className="check-label"><input type="checkbox" checked={kept} onChange={event => setKept(event.target.checked)} />Lock placement</label>
          <small>Auto-place won’t move this account.</small>
          <button className="primary" type="submit">{busy ? 'Saving…' : 'Save changes'}</button>
        </fieldset>
      </form>}
      {canRoster && <small>Changes apply to the working roster. Publish again to update the published roster.</small>}
      {(localError || error) && <p role="alert">{localError || error}</p>}
      {archived && <p>Archived season · account changes are unavailable.</p>}
      {canSignups && !archived && (
        <section className="roster-player-signup" aria-label="Signup actions">
          <h3>Signup type</h3>
          <p>{account.pool === 'main' ? 'Main CWL' : 'Lazy CWL'} · Changing type clears this account’s working placement.</p>
          {onPoolChange && (!poolReview ? (
            <button type="button" disabled={busy || dirty} onClick={() => setPoolReview(account.pool === 'main' ? 'lazy' : 'main')}>
              Switch to {account.pool === 'main' ? 'Lazy' : 'Main'} CWL
            </button>
          ) : (
            <div className="roster-player-pool-review" role="group" aria-label="Review signup type change">
              <strong>Move {account.player_name} to {poolReview === 'main' ? 'Main' : 'Lazy'} CWL?</strong>
              <small>Any working hosting-clan assignment will be cleared. Published rosters stay unchanged until republished. Main CWL eligibility is checked before saving.</small>
              <div>
                <button type="button" disabled={busy} onClick={() => setPoolReview(null)}>Cancel</button>
                <button type="button" className="primary" disabled={busy} onClick={() => void changePool()}>{busy ? 'Saving…' : 'Confirm signup change'}</button>
              </div>
            </div>
          ))}
          <div className="roster-player-remove">
            <button className="danger" disabled={busy || !!poolReview || dirty} onClick={() => void remove()}>Remove signup</button>
            <small>Removes this season’s signup and placement. Saved weights stay.</small>
          </div>
        </section>
      )}
    </dialog>,
    document.body,
  )
}
