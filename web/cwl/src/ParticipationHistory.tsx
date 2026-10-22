import { useEffect, useState } from 'react';
import { api, ApiError } from './api';
import type { ParticipationData } from './participation';

/** Historical results are read only and fetched only while expanded. */
export default function ParticipationHistory({ seasonId, onAccessDenied }: { seasonId: string; onAccessDenied: (error: ApiError) => void }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<ParticipationData | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setData(null);
    setError('');
    api<ParticipationData>(`/seasons/${encodeURIComponent(seasonId)}/participation?source=history`)
      .then(result => { if (active) setData(result); })
      .catch(cause => {
        if (!active) return;
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) onAccessDenied(cause);
        else setError(cause instanceof Error ? cause.message : 'Could not load history.');
      });
    return () => { active = false; };
  }, [open, seasonId, attempt]);

  return <details className="participation-history" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Saved results history · read only</summary>
    {open && <>
      <p>Previously recorded accounts and clan assignments, including removed signups. This list does not add accounts to current results or bonus draws.</p>
      {error && <p role="alert">{error} <button type="button" onClick={() => setAttempt(value => value + 1)}>Retry history</button></p>}
      {!data && !error && <p role="status">Loading history…</p>}
      {data && !data.accounts.length && <p>No saved results yet.</p>}
      {data?.accounts.map(account => <div className="participation-history-row" key={account.tag}>
        <strong>{account.player_name}</strong>
        <span>{account.tag} · {account.pool === 'main' ? 'Main CWL' : 'Lazy CWL'} · {account.assigned_clan_name || account.assigned_clan_tag || 'Unassigned'}</span>
        <span>Attacks {account.attacks ?? 'Not available'} · Stars {account.stars ?? 'Not available'}</span>
        {account.notes && <p>{account.notes}</p>}
      </div>)}
    </>}
  </details>;
}
