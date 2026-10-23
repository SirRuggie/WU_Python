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
  return <ConfirmDialog heading="Change CWL pool?"
    text={subject}
    confirmLabel={`Choose ${to}`} disabled={disabled} onCancel={onCancel} onConfirm={onConfirm}>
    <div className="pool-change-content">
      <p className="pool-change-direction"><strong>{from}</strong><span aria-label="to">→</span><strong>{to}</strong></p>
      <img className="pool-change-animation" src={animation} width={480} height={480}
        alt="Tim Robinson asking: You sure about that?" />
      <p className="pool-change-summary">{destination === 'lazy'
        ? 'Lazy CWL: for FWA players or players upgrading heroes.'
        : 'Main CWL: play to win. All heroes must be ready.'}</p>
      {rows.some(row => row.has_staff_placement) && <p className="pool-change-warning">Saving removes your clan placement and notifies staff.</p>}
      <p className="pool-change-save-note">Next: select <strong>Save changes</strong> to finish.</p>
    </div>
  </ConfirmDialog>
}
