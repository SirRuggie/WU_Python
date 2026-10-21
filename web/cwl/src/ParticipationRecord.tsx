import { useEffect, useState } from 'react';
import { canUseSyncedResults, parseOptionalCount, participationValidation, syncStatusLabel, type ParticipationAccount } from './participation';
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Could not save results.';
const dateText = (value: string) => new Date(value).toLocaleString();
export default function ParticipationRecord({ account, publicationVersion, archived, onSave, onReset, onDirty }: {
    account: ParticipationAccount;
    publicationVersion: number | null;
    archived: boolean;
    onSave: (account: ParticipationAccount, revision: number, publicationVersion: number | null, sourceCheckedAt: string | null, attacks: number | null, stars: number | null, notes: string) => Promise<ParticipationAccount>;
    onReset: (account: ParticipationAccount) => Promise<ParticipationAccount>;
    onDirty: (tag: string, dirty: boolean) => void;
}) {
    const values = (row: ParticipationAccount) => ({ attacks: row.attacks === null ? '' : String(row.attacks), stars: row.stars === null ? '' : String(row.stars), notes: row.notes });
    const [draft, setDraft] = useState(() => values(account));
    const [base, setBase] = useState(() => ({ ...values(account), revision: account.revision, publicationVersion, rosterToken: account.roster_token, sourceCheckedAt: account.source_checked_at ?? null }));
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const changed = draft.attacks !== base.attacks || draft.stars !== base.stars || draft.notes !== base.notes;
    const latestValues = values(account);
    const stale = account.roster_token !== base.rosterToken || account.revision !== base.revision || publicationVersion !== base.publicationVersion || (account.source_checked_at ?? null) !== base.sourceCheckedAt || latestValues.attacks !== base.attacks || latestValues.stars !== base.stars || latestValues.notes !== base.notes;
    useEffect(() => {
        if (changed || !stale)
            return;
        const latest = values(account);
        setDraft(latest);
        setBase({ ...latest, revision: account.revision, publicationVersion, rosterToken: account.roster_token, sourceCheckedAt: account.source_checked_at ?? null });
    }, [account, publicationVersion, changed, stale]);
    useEffect(() => { onDirty(account.tag, changed || busy); return () => onDirty(account.tag, false); }, [account.tag, changed, busy, onDirty]);
    const attackValue = parseOptionalCount(draft.attacks);
    const starValue = parseOptionalCount(draft.stars);
    const validation = attackValue === undefined || starValue === undefined ? 'Use whole numbers for attacks and stars, or leave them blank.' : participationValidation(attackValue, starValue, draft.notes);
    const useLatest = () => { const latest = values(account); setDraft(latest); setBase({ ...latest, revision: account.revision, publicationVersion, rosterToken: account.roster_token, sourceCheckedAt: account.source_checked_at ?? null }); setError(''); };
    const save = async () => {
        if (archived || !changed || stale || validation || attackValue === undefined || starValue === undefined)
            return;
        setBusy(true);
        setError('');
        try {
            const saved = await onSave({ ...account, roster_token: base.rosterToken }, base.revision, base.publicationVersion, base.sourceCheckedAt, attackValue, starValue, draft.notes);
            const latest = values(saved);
            setDraft(latest);
            setBase({ ...latest, revision: saved.revision, publicationVersion, rosterToken: saved.roster_token, sourceCheckedAt: saved.source_checked_at ?? null });
        }
        catch (cause) {
            setError(errorText(cause));
        }
        finally {
            setBusy(false);
        }
    };
    const hasOverride = !!(account.attacks_override || account.stars_override || account.roster_changed);
    const hasSource = account.source_attacks !== null && account.source_attacks !== undefined || account.source_stars !== null && account.source_stars !== undefined;
    const canReset = canUseSyncedResults(account);
    const reset = async () => {
        if (archived || busy || changed || stale || !canReset)
            return;
        const partial = !account.source_complete ? ' These source results are partial and may change.' : '';
        if (!window.confirm(`Replace manual attack and star overrides for ${account.player_name} with the synced source values? Staff notes will remain.${partial}`))
            return;
        setBusy(true);
        setError('');
        try {
            const saved = await onReset(account);
            const latest = values(saved);
            setDraft(latest);
            setBase({ ...latest, revision: saved.revision, publicationVersion, rosterToken: saved.roster_token, sourceCheckedAt: saved.source_checked_at ?? null });
        }
        catch (cause) {
            setError(errorText(cause));
        }
        finally {
            setBusy(false);
        }
    };
    return <article className="card participation-card">
    <div className="participation-card-head">
      <div>
      <h3>{account.player_name}</h3>
      <small>{account.tag} · TH {account.town_hall ?? '—'} · {account.pool === 'main' ? 'Main Clan CWL' : 'Lazy CWL'}</small>
      <small>Hosting clan: {account.assigned_clan_name || account.assigned_clan_tag || 'Awaiting placement'}</small>
      </div>
      <span className="badge">{'Current signup'}</span>
      </div>
    {account.roster_changed && <div className="inline-reason" role="alert">Saved results belong to a previous assignment. {account.assigned_clan_tag ? 'Refresh Clash results, then use synced results to replace old corrections.' : 'Assign this account to a CWL clan in Roster, then refresh Clash results.'} Staff notes stay saved.
      {account.previous_results && <details>
      <summary>Previous assignment &amp; corrections</summary>
      <p>{account.previous_results.pool === 'main' ? 'Main CWL' : 'Lazy CWL'} · {account.previous_results.assigned_clan_name || account.previous_results.assigned_clan_tag || 'Unassigned'} · Attacks {account.previous_results.attacks ?? 'Not available'} · Stars {account.previous_results.stars ?? 'Not available'}</p>
      </details>}
    </div>}
    <p className="participation-totals">
      <strong>Attacks {account.attacks ?? 'Not available'}</strong>
      <span>Stars {account.stars ?? 'Not available'}</span>
      <small>{syncStatusLabel(account.source_status)}</small>
      </p>
    {(account.source_warning || ['stale', 'unavailable'].includes(account.source_status || '')) && <p className="inline-reason">{account.source_warning || 'Source data is not freshly verified. Review before using results.'}</p>}
    <details className="participation-editor">
      <summary>Corrections &amp; notes · Attacks {draft.attacks || '—'} · Stars {draft.stars || '—'}{changed ? ' · Unsaved changes' : ''}{error ? ' · Save failed' : ''}</summary>
    <div className="participation-source">
      <strong>Synced CWL result</strong>
      <span>Attacks {account.source_attacks ?? 'Unrecorded'} · Stars {account.source_stars ?? 'Unrecorded'}</span>
      <small>{syncStatusLabel(account.source_status)}{hasSource ? account.source_complete ? ' · Final results' : ' · Partial results' : ''}{account.source_checked_at ? ` · Checked ${dateText(account.source_checked_at)}` : ''}</small>{account.source_warning && <small className="participation-error">{account.source_warning}</small>}{!account.source_warning && !account.source_complete && hasSource && <small className="participation-error">Source observations are incomplete; synced totals may change.</small>}{['stale', 'unavailable'].includes(account.source_status || '') && <small className="participation-error">Source data is not freshly verified. Review before using synced results.</small>}{hasOverride && <small>Manual correction in use{account.attacks_override && account.stars_override ? ' for attacks and stars' : account.attacks_override ? ' for attacks' : ' for stars'}.</small>}{hasOverride && <button disabled={archived || busy || changed || stale || !hasSource} onClick={() => void reset()}>Use synced results</button>}{hasOverride && !hasSource && <small>Synced values are unavailable, so the manual correction cannot be reset yet.</small>}{hasOverride && changed && <small>Save or discard your unsaved entry before using synced results.</small>}</div>
    <div className="participation-fields">
      <label>Current attacks<input type="number" min="0" max="7" step="1" inputMode="numeric" value={draft.attacks} disabled={archived || busy || !!account.roster_changed} onChange={event => setDraft(current => ({ ...current, attacks: event.target.value }))} placeholder="Unrecorded"/>
      </label>
      <label>Current stars<input type="number" min="0" max="21" step="1" inputMode="numeric" value={draft.stars} disabled={archived || busy || !!account.roster_changed} onChange={event => setDraft(current => ({ ...current, stars: event.target.value }))} placeholder="Unrecorded"/>
      </label>
      </div>
    <label className="participation-notes">Staff notes<textarea rows={3} maxLength={2000} value={draft.notes} disabled={archived || busy || !!account.roster_changed} onChange={event => setDraft(current => ({ ...current, notes: event.target.value }))} placeholder="Optional manual note"/>
      </label>
    {stale && changed && <div className="inline-reason">This record or current assignment changed while you were editing. Your unsaved entry is still here. Review the latest values before saving.<button onClick={useLatest} disabled={busy}>Discard entry and use latest values</button>
      </div>}
    <div className="participation-card-foot">
      <div>{validation && changed && <small role="alert" className="participation-error">{validation}</small>}{error && <small role="alert" className="participation-error">{error}</small>}{account.updated_at && <small>Last saved {dateText(account.updated_at)}{account.updated_by ? ` by ${account.updated_by}` : ''}</small>}</div>
      <button className="primary" disabled={archived || busy || !!account.roster_changed || !changed || stale || !!validation} onClick={() => void save()}>{busy ? 'Saving…' : 'Save record'}</button>
      </div>
    </details>
  </article>;
}
