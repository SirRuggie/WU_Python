import type { Pool, Signup } from './api'
import ConfirmDialog from './ConfirmDialog'
import animation from './assets/confirm-pool-change.gif'
import './PoolChangeDialog.css'

export default function PoolChangeDialog({ rows, destination, disabled, onCancel, onConfirm }: {
  rows: Signup[]
  destination: Pool
  disabled: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const from = destination === 'lazy' ? 'Main CWL' : 'Lazy CWL'
  const to = destination === 'lazy' ? 'Lazy CWL' : 'Main CWL'
  const subject = rows.length === 1 ? rows[0].player_name || rows[0].tag : `${rows.length} accounts`
  return <ConfirmDialog heading="You sure about that?"
    text={`${subject}: currently in ${from}. You’re choosing to move to ${to}.`}
    confirmLabel={`Continue to ${to}`} disabled={disabled} onCancel={onCancel} onConfirm={onConfirm}>
    <img className="pool-change-animation" src={animation} width={480} height={480}
      alt="Tim Robinson asking: You sure about that?" />
    <p>{destination === 'lazy'
      ? 'Lazy CWL is the relaxed option for players who normally play FWA, have heroes upgrading, or want stress-free CWL while upgrading their village.'
      : 'Main CWL is for players aiming to win at full strength, with heroes available and no heroes upgrading.'}</p>
    {rows.some(row => row.has_staff_placement) && <p>Saving this change removes the current working placement and alerts staff.</p>}
    <p className="small">You’ll still need to select Save changes to finish. Cancel keeps your current pool.</p>
  </ConfirmDialog>
}
