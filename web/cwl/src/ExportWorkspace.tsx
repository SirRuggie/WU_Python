import { useRef, useState } from 'react'
import type { Season } from './api'

type Props = { seasonId: string; seasons: Season[]; onSeasonChange: (id: string) => void }
export default function ExportWorkspace({ seasonId, seasons, onSeasonChange }: Props) {
  const [kind, setKind] = useState('accounts')
  const [basis, setBasis] = useState('current')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const downloading = useRef(false)
  const download = async () => {
    if (!seasonId || downloading.current) return
    downloading.current = true
    setBusy(true); setNotice(''); setError('')
    try {
      const response = await fetch(`/api/cwl/seasons/${encodeURIComponent(seasonId)}/export.csv?kind=${kind}&basis=${basis}`, { credentials: 'same-origin' })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.error || 'Could not download this export. Sign in again or retry.')
      }
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url; link.download = `cwl-season-${seasonId}-${kind}-${basis}.csv`
      document.body.appendChild(link); link.click(); link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setNotice('CSV download started. Check your browser downloads.')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Export failed. Please try again.') }
    finally { downloading.current = false; setBusy(false) }
  }
  return <div><div className="page-head"><div><p className="eyebrow">Staff tools</p><h1>Export season</h1><p>Download current or archived season records for your spreadsheet.</p></div><label className="season-choice">Season<select disabled={busy} value={seasonId} onChange={event => { onSeasonChange(event.target.value); setNotice(''); setError('') }}><option value="">Select a season</option>{seasons.map(season => <option value={String(season.id)} key={season.id}>{season.label}{season.status === 'archived' ? ' · Archived' : ''}</option>)}</select></label></div>{error && <div className="notice error" role="alert">{error}</div>}{notice && <div className="notice success" role="status">{notice}</div>}<section className="card narrow"><label>Export type<select disabled={busy} value={kind} onChange={event => { setKind(event.target.value); setNotice(''); setError('') }}><option value="accounts">Accounts, weights &amp; results</option><option value="participation">Complete participation history</option><option value="bonus-history">Bonus selection history</option></select></label>{kind === 'accounts' && <label style={{ marginTop: 16 }}>Roster version<select disabled={busy} value={basis} onChange={event => { setBasis(event.target.value); setNotice(''); setError('') }}><option value="current">Current saved placements</option><option value="published">Latest published roster</option></select></label>}<p style={{ marginTop: 16 }}>{kind === 'accounts' ? 'One row per account, with clan, weights, results and bonus status. Results keep the clan and Main/Lazy group recorded at the time.' : kind === 'participation' ? 'All saved results, including removed accounts, staff corrections and notes.' : 'Saved bonus selections, including cancelled records, reasons and dates. This does not confirm in-game awards.'}</p><p className="small">Unknown results stay blank. Weights use full numbers (174000 = 174k). Discord IDs stay complete. Names and notes are protected from running as spreadsheet formulas.</p><button className="primary" disabled={busy || !seasonId} onClick={() => void download()}>{busy ? 'Preparing CSV…' : 'Download CSV'}</button></section></div>
}
