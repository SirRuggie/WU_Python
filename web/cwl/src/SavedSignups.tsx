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
  onMove: (rows: Signup[], pool: Pool) => void
  onWithdraw: (rows: Signup[]) => void
}
const poolName = (pool: Pool) => pool === 'main' ? 'Main CWL' : 'Lazy CWL'

export default function SavedSignups({signups, accounts, editable, busy, canMove, headingRef, onMove, onWithdraw}: Props) {
  const [selecting, setSelecting] = useState(false)
  const [tags, setTags] = useState<string[]>([])
  const available = signups.filter(row => !row.has_staff_placement)
  const selected = available.filter(row => tags.includes(row.tag))
  const movable = (pool: Pool) => selected.filter(row => row.pool !== pool)
  const canMoveRows = (rows: Signup[]) => canMove && rows.length > 0 && rows.every(row => accounts.some(account => account.tag === row.tag))
  return <>
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
        {(['main','lazy'] as Pool[]).map(pool => <button key={pool} disabled={busy || !canMoveRows(movable(pool))} onClick={() => onMove(movable(pool), pool)}>Move to {poolName(pool)} ({movable(pool).length})</button>)}
        <button className="withdraw-button" disabled={busy || !selected.length} onClick={() => onWithdraw(selected)}>Withdraw selected ({selected.length})</button>
      </div>
      <small>Moves open a review before saving. Accounts already in that pool stay there. Staff-placed accounts cannot be selected.</small>
      {selected.some(row => !accounts.some(account => account.tag === row.tag)) && <small>Some accounts could not be found in your linked accounts. Refresh accounts before moving them.</small>}
    </div>}
    <div className="registered-grid">{signups.map(signup => <div className="card registered-card" key={signup.tag}>
      <div className="saved-signup-account">
        {selecting && editable && <input type="checkbox" aria-label={`Select ${signup.player_name || signup.tag} ${signup.tag}`} disabled={busy || !!signup.has_staff_placement} checked={!signup.has_staff_placement && tags.includes(signup.tag)} onChange={event => setTags(current => event.target.checked ? [...current,signup.tag] : current.filter(tag => tag !== signup.tag))}/>}
        <div><strong className="signed-up-name"><TownHallIcon level={accounts.find(account => account.tag === signup.tag)?.town_hall ?? signup.town_hall}/><span>{signup.player_name || accounts.find(account => account.tag === signup.tag)?.name || signup.tag}</span></strong>
          <small>{signup.tag} · {poolName(signup.pool)}</small><small>Clan at signup: {signup.signup_clan_name || signup.signup_clan_tag || 'Not available'}</small>
          {signup.has_staff_placement && <p className="inline-reason">Staff have placed this account. Ask staff to change or withdraw its signup.</p>}
        </div>
      </div>
      {!selecting && editable && !signup.has_staff_placement && <div className="registered-actions">
        <button disabled={busy || !canMoveRows([signup])} onClick={() => onMove([signup], signup.pool === 'main' ? 'lazy' : 'main')}>Change CWL pool</button>
        <button className="withdraw-button" disabled={busy} onClick={() => onWithdraw([signup])}>Withdraw signup</button>
      </div>}
    </div>)}</div>
  </>
}
