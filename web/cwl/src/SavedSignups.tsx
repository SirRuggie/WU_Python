import PoolChangeDialog from './PoolChangeDialog'
import {poolChangeDecision} from './signupMoves'
import FwaSignupDialog from './FwaSignupDialog'
import useUnsavedWork from './useUnsavedWork'
import type {SignupMove} from './signupMoves'
import {useState, type RefObject} from 'react'
import type {Account, Pool, Signup} from './api'
import TownHallIcon from './TownHallIcon'
import './SavedSignups.css'

type Props = {
  signups: Signup[]
  accounts: Account[]
  editable: boolean
  busy: boolean
  canMove: boolean
  headingRef: RefObject<HTMLHeadingElement | null>
  onSave: (moves: SignupMove[]) => Promise<{saved: string[]; error: string | null}>
  onDirty: (dirty: boolean) => void
  onWithdraw: (rows: Signup[]) => void
}
const poolName = (pool: Pool) => pool === 'main' ? 'Main CWL' : 'Lazy CWL'

export default function SavedSignups({signups, accounts, editable, busy, canMove, headingRef, onSave, onDirty, onWithdraw}: Props) {
  const [poolConfirmation, setPoolConfirmation] = useState<{rows: Signup[]; pool: Pool} | null>(null)
  const [fwaBlocked, setFwaBlocked] = useState(false)
  const [selecting, setSelecting] = useState(false)
  const [tags, setTags] = useState<string[]>([])
  const [saveError, setSaveError] = useState<string | null>(null)
  const [moves, setMoves] = useState<Record<string, Pool>>({})
  useUnsavedWork(Object.keys(moves).length > 0, onDirty)
  const changes = signups.filter(row => moves[row.tag] && moves[row.tag] !== row.pool).map(signup => ({signup, destination: moves[signup.tag]}))
  const stage = (rows: Signup[], pool: Pool, confirmed = false) => {
    if (busy || !editable || !canMove) return
    // Recheck the saved pool and current links when confirming an open dialog.
    if (rows.some(row => !signups.some(current => current.tag === row.tag && current.pool === row.pool))) {
      setPoolConfirmation(null)
      setSaveError('These signups changed. Refresh before changing pools.')
      return
    }
    const decision = poolChangeDecision(rows, pool, accounts)
    if (decision === 'unavailable') {
      setPoolConfirmation(null)
      setSaveError('Account links changed. Refresh accounts before changing pools.')
      return
    }
    setSaveError(null)
    if (decision === 'fwa') {
      setPoolConfirmation(null)
      setFwaBlocked(true)
      return
    }
    if (decision === 'confirm' && !confirmed) {
      setPoolConfirmation({rows, pool})
      return
    }
    setPoolConfirmation(null)
    setMoves(current => {
      const next = {...current}
      for (const row of rows) { if (row.pool === pool) delete next[row.tag]; else next[row.tag] = pool }
      return next
    })
  }
  const save = async () => {
    const result = await onSave(changes)
    setSaveError(result.error)
    setMoves(current => Object.fromEntries(Object.entries(current).filter(([tag]) => !result.saved.includes(tag))))
  }
  const available = signups
  const selected = available.filter(row => tags.includes(row.tag))
  const movable = (pool: Pool) => selected.filter(row => (moves[row.tag] || row.pool) !== pool)
  const canMoveRows = (rows: Signup[]) => canMove && rows.length > 0 && rows.every(row => accounts.some(account => account.tag === row.tag))
  return <>
    {poolConfirmation && <PoolChangeDialog
      rows={poolConfirmation.rows.filter(row => row.pool !== poolConfirmation.pool)}
      destination={poolConfirmation.pool} disabled={busy || !editable || !canMove}
      onCancel={() => setPoolConfirmation(null)}
      onConfirm={() => stage(poolConfirmation.rows, poolConfirmation.pool, true)}
    />}
    {fwaBlocked && <FwaSignupDialog onClose={() => setFwaBlocked(false)} />}
    {saveError && <p className="notice error" role="alert">{saveError}</p>}
    <div className="section-heading">
      <div><p className="eyebrow">Saved this season</p><h2 ref={headingRef} tabIndex={-1}>Signed-up accounts</h2></div>
      {editable && signups.length > 0 && <button disabled={busy} aria-pressed={selecting} onClick={() => {setSelecting(!selecting);setTags([])}}>{selecting ? 'Cancel selection' : 'Select accounts'}</button>}
    </div>
    {selecting && editable && <div className="saved-signup-toolbar" aria-label="Selected signup actions">
      <div className="saved-signup-selection">
        <label><input type="checkbox" disabled={busy || !available.length} checked={available.length > 0 && selected.length === available.length} ref={node => {if (node) node.indeterminate = selected.length > 0 && selected.length < available.length}} onChange={event => setTags(event.target.checked ? available.map(row => row.tag) : [])}/>Select all available ({available.length})</label>
        <span role="status">{selected.length} selected</span>
        <button disabled={busy || !selected.length} onClick={() => setTags([])}>Clear</button>
      </div>
      <div className="saved-signup-actions">
        {(['main','lazy'] as Pool[]).map(pool => <button key={pool} disabled={busy || !canMoveRows(movable(pool))} onClick={() => stage(movable(pool), pool)}>Move to {poolName(pool)} ({movable(pool).length})</button>)}
        <button className="withdraw-button" disabled={busy || !!changes.length || !selected.length} onClick={() => onWithdraw(selected)}>Withdraw selected ({selected.length})</button>
      </div>
      <small>Changes stay here until you select Save changes. Accounts already in that pool stay there. Staff will be alerted to withdrawals and pool changes.</small>
      {selected.some(row => !accounts.some(account => account.tag === row.tag)) && <small>Some accounts could not be found in your linked accounts. Refresh accounts before moving them.</small>}
    </div>}
    <div className="registered-grid">{signups.map(signup => <div className={`card registered-card saved-signup-card ${moves[signup.tag] && moves[signup.tag] !== signup.pool ? 'pool-change-pending' : selecting && tags.includes(signup.tag) ? 'account-selected' : ''}`} key={signup.tag}>
      <div className="saved-signup-account">
        {selecting && editable && <input type="checkbox" aria-label={`Select ${signup.player_name || signup.tag} ${signup.tag}`} disabled={busy} checked={tags.includes(signup.tag)} onChange={event => setTags(current => event.target.checked ? [...current,signup.tag] : current.filter(tag => tag !== signup.tag))}/>}
        <div><strong className="signed-up-name"><TownHallIcon level={accounts.find(account => account.tag === signup.tag)?.town_hall ?? signup.town_hall}/><span>{signup.player_name || accounts.find(account => account.tag === signup.tag)?.name || signup.tag}</span></strong>
          <small>{signup.tag} · {poolName(signup.pool)}</small><small>Clan at signup: {signup.signup_clan_name || signup.signup_clan_tag || 'Not available'}</small>
          {moves[signup.tag] && moves[signup.tag] !== signup.pool && <p className="inline-reason pending-switch" role="status"><strong>Not saved</strong> — switching from {poolName(signup.pool)} to {poolName(moves[signup.tag])}.<small>Select Save changes to finish.</small></p>}
          {(moves[signup.tag] || signup.pool) === 'main' && accounts.find(account => account.tag === signup.tag)?.current_clan_type === 'FWA' && <p className="inline-reason">This account is currently in FWA and can only choose Lazy CWL.</p>}
          {canMove && !busy && !accounts.some(account => account.tag === signup.tag) && <p className="inline-reason">This account is not in your current linked accounts. Check its Discord link, then refresh before changing pools.</p>}
          {signup.has_staff_placement && <p className="inline-reason">Changing pools or withdrawing will remove this working placement and alert staff.</p>}
        </div>
      </div>
      {!selecting && editable && <div className="registered-actions">
        <button disabled={busy || !canMoveRows([signup])} onClick={() => stage([signup], (moves[signup.tag] || signup.pool) === 'main' ? 'lazy' : 'main')}>{moves[signup.tag] ? 'Undo change' : 'Change CWL pool'}</button>
        <button className="withdraw-button" disabled={busy || !!changes.length} onClick={() => onWithdraw([signup])}>Withdraw signup</button>
      </div>}
    </div>)}</div>
    {changes.length > 0 && <div className="saved-signup-savebar" aria-label="Pending CWL changes">
      <span>{changes.length} {changes.length === 1 ? 'change' : 'changes'} · Not saved yet</span>
      <button disabled={busy} onClick={() => {setMoves({});setSaveError(null)}}>Cancel</button>
      <button className="primary" disabled={busy || !editable || !changes.every(change => canMoveRows([change.signup]))} onClick={() => void save()}>{busy ? 'Saving…' : 'Save changes'}</button>
    </div>}
  </>
}
