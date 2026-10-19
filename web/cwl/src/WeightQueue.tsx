import { useState } from 'react'
import TownHallIcon from './TownHallIcon'
import { parseManualWeightK, type RosterAccount } from './roster'
import './WeightQueue.css'

type Props = { accounts: RosterAccount[]; busy: boolean; onEdit: (tag: string) => void; onSave: (tag: string, weight: number) => Promise<boolean>; onRefresh: () => void; onClose: () => void }
export default function WeightQueue({ accounts, busy, onEdit, onSave, onRefresh, onClose }: Props) {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const missing = accounts.filter(account => account.effective_weight === null)
  const query = search.trim().toLocaleLowerCase()
  const matching = missing.filter(account => `${account.player_name} ${account.tag}`.toLocaleLowerCase().includes(query))
  const lastPage = Math.max(0, Math.ceil(matching.length / 10) - 1)
  const currentPage = Math.min(page, lastPage)
  return <section className="card weight-queue" aria-labelledby="weight-queue-title">
    <div className="card-heading"><h2 id="weight-queue-title">Needs weight · {missing.length}</h2><button onClick={onClose}>Back to roster</button></div>
    <p>Refresh FWA Stats first. If an account is still missing, enter its known war weight below. Saved accounts leave this list automatically.</p>
    <div className="weight-queue-tools"><button disabled={busy} onClick={onRefresh}>↻ Bulk refresh FWA weights</button><label>Find account<input type="search" value={search} onChange={event => { setSearch(event.target.value); setPage(0) }} placeholder="Name or player tag" /></label></div>
    <p className="small">Refresh checks all season signups and preserves manual weights. Enter thousands: 174 = 174,000. Saving a weight does not move the account.</p>
    {!missing.length ? <div role="status"><h3>All accounts have a weight ✓</h3><p>Return to the roster to preview automatic placement.</p></div> : !matching.length ? <p>No missing-weight accounts match your search.</p> : matching.slice(currentPage * 10, (currentPage + 1) * 10).map(account => <WeightRow key={account.tag} account={account} busy={busy} onEdit={onEdit} onSave={onSave} />)}
    {lastPage > 0 && <nav aria-label="Missing weight pages"><button disabled={currentPage===0 || busy} onClick={() => setPage(currentPage-1)}>← Previous</button><span>{currentPage+1} / {lastPage+1}</span><button disabled={currentPage===lastPage || busy} onClick={() => setPage(currentPage+1)}>Next →</button></nav>}
  </section>
}
function WeightRow({ account, busy, onEdit, onSave }: Pick<Props, 'busy' | 'onEdit' | 'onSave'> & { account: RosterAccount }) {
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  return <form className="weight-queue-row" onSubmit={async event => {
    event.preventDefault()
    try {
      const weight = parseManualWeightK(value)
      if (weight === null) throw new Error('Enter a known weight before saving.')
      setError('')
      const saved = await onSave(account.tag, weight)
      if (saved) setValue('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Weight could not be saved.') }
  }}><div className="weight-queue-identity"><TownHallIcon level={account.town_hall}/><div><button type="button" className="roster-player-name" disabled={busy} onClick={()=>onEdit(account.tag)} title="Edit account">{account.player_name}</button><small>{account.tag} · {account.pool==='lazy'?'Lazy':'Main'} CWL</small><small>{account.source_status==='unavailable'?'FWA source unavailable':'No saved FWA weight'}</small></div></div><label>Weight (k)<input aria-label={`Weight for ${account.player_name} (${account.tag}) in thousands`} type="number" inputMode="decimal" min="0.001" max="500" step="0.001" value={value} onChange={event => setValue(event.target.value)} placeholder="e.g. 174" disabled={busy} required /></label><button className="primary" disabled={busy || !value.trim()}>Save weight</button>{error && <p className="inline-reason" role="alert">{error}</p>}</form>
}
