export default function ClanActivityStatus({error, busy, checkedAt, warnings, refresh}: {
  error: string; busy: boolean; checkedAt?: string; warnings: string[]; refresh: () => void
}) {
  return <>
    <div className="activity-refresh"><span role="status">{busy ? 'Checking clan activity…' : checkedAt ? `Checked ${new Date(checkedAt).toLocaleTimeString()}` : 'Not checked yet'}{error && checkedAt ? ' · Showing the last update' : ''}</span><button onClick={refresh} disabled={busy}>{busy ? 'Checking…' : 'Refresh'}</button></div>
    {error && <p role="alert" className="notice error">{error}</p>}
    {warnings.map(note => <p className="notice" role="status" key={note}>{note}</p>)}
  </>
}
