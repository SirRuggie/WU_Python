import './ParticipationWorkspace.css';
import CwlPoolTabs, { useCwlPool } from './CwlPoolTabs';
import ParticipationRecord from './ParticipationRecord';
import ParticipationHistory from './ParticipationHistory';
import useUnsavedWork from './useUnsavedWork';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, type Season } from './api';
import { validCwlCycle, visibleParticipation, syncStatusLabel, type ParticipationAccount, type ParticipationData, type ParticipationSort, type ParticipationSync } from './participation';
type Props = {
    seasonId: string;
    seasons: Season[];
    onDirty?: (dirty: boolean) => void;
    onSeasonChange: (id: string) => void;
};
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Results could not be loaded. Try again.';
const dateText = (value: string) => new Date(value).toLocaleString();
export default function ParticipationWorkspace({ seasonId, seasons, onSeasonChange, onDirty: reportDirty }: Props) {
    const [data, setData] = useState<ParticipationData | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState<{
        text: string;
        kind: 'success' | 'error';
    } | null>(null);
    const [dirtyTags, setDirtyTags] = useState<Set<string>>(new Set());
    const [syncDraft, setSyncDraft] = useState<{
        cycle: string;
        enabled: boolean;
    } | null>(null);
    const [syncDirty, setSyncDirty] = useState(false);
    const syncDirtyRef = useRef(false);
    syncDirtyRef.current = syncDirty;
    const [syncBusy, setSyncBusy] = useState(false);
    const [syncError, setSyncError] = useState('');
    useUnsavedWork(dirtyTags.size > 0 || syncDirty || syncBusy, reportDirty);
    const onDirty = useCallback((tag: string, dirty: boolean) => setDirtyTags(current => { if (current.has(tag) === dirty)
        return current; const next = new Set(current); if (dirty)
        next.add(tag);
    else
        next.delete(tag); return next; }), []);
    const changeSeason = (id: string) => { if ((dirtyTags.size || syncDirty) && !window.confirm(`Discard ${dirtyTags.size ? `unsaved manual results for ${dirtyTags.size} account${dirtyTags.size === 1 ? '' : 's'}` : 'unsaved sync settings'}?`))
        return; setDirtyTags(new Set()); onSeasonChange(id); };
    const [page, setPage] = useState(0);
    const [search, setSearch] = useState('');
    const [pool, setPool] = useCwlPool();
    const [clan, setClan] = useState('all');
    const [sort, setSort] = useState<ParticipationSort>('name');
    const requestId = useRef(0);
    const currentSeason = useRef(seasonId);
    currentSeason.current = seasonId;
    const load = useCallback(async () => {
        if (!seasonId)
            return;
        const sid = seasonId, id = ++requestId.current;
        setLoading(true);
        setError('');
        try {
            const result = await api<ParticipationData>(`/seasons/${encodeURIComponent(sid)}/participation`);
            if (id === requestId.current && currentSeason.current === sid) {
                setData(result);
                if (result.sync && !syncDirtyRef.current)
                    setSyncDraft({ cycle: result.sync.cycle || '', enabled: result.sync.enabled });
            }
        }
        catch (cause) {
            if (id === requestId.current && currentSeason.current === sid) {
                setError(errorText(cause));
                if (cause instanceof ApiError && [401, 403].includes(cause.status))
                    setData(null);
            }
        }
        finally {
            if (id === requestId.current && currentSeason.current === sid)
                setLoading(false);
        }
    }, [seasonId]);
    useEffect(() => { requestId.current += 1; setData(null); setError(''); setNotice(null); setDirtyTags(new Set()); setSyncDraft(null); setSyncDirty(false); setSyncError(''); setSearch(''); setClan('all'); setSort('name'); if (seasonId)
        void load(); }, [seasonId, load]);
    const saveSyncSettings = async () => {
        if (!seasonId || !syncDraft || syncBusy || archived || !validCwlCycle(syncDraft.cycle))
            return;
        const sid = seasonId;
        const cycleChanged = syncDraft.cycle !== data?.sync?.cycle;
        if (cycleChanged && dirtyTags.size && !window.confirm(`Changing the CWL month will discard unsaved result edits for ${dirtyTags.size} account${dirtyTags.size === 1 ? '' : 's'}. Continue?`))
            return;
        setSyncBusy(true);
        setSyncError('');
        try {
            const result = await api<{
                sync: ParticipationSync;
            }>(`/seasons/${encodeURIComponent(sid)}/participation/sync-settings`, 'POST', syncDraft);
            if (currentSeason.current !== sid)
                return;
            setSyncDirty(false);
            syncDirtyRef.current = false;
            if (cycleChanged) {
                setData(null);
                setDirtyTags(new Set());
            }
            else
                setData(current => current ? { ...current, sync: result.sync } : current);
            await load();
            if (currentSeason.current === sid)
                setNotice({ kind: 'success', text: result.sync.enabled ? 'Automatic CWL results sync enabled.' : 'Automatic CWL results sync disabled. Sync now remains available.' });
        }
        catch (cause) {
            if (currentSeason.current === sid && cause instanceof ApiError && [401, 403].includes(cause.status)) setData(null);
            if (currentSeason.current === sid)
                setSyncError(errorText(cause));
        }
        finally {
            setSyncBusy(false);
        }
    };
    const syncNow = async () => {
        if (!seasonId || syncBusy || archived || !data?.sync?.cycle || syncDirty)
            return;
        const sid = seasonId;
        setSyncBusy(true);
        setSyncError('');
        try {
            const result = await api<{
                sync: ParticipationSync;
                updated_accounts: number;
            }>(`/seasons/${encodeURIComponent(sid)}/participation/sync`, 'POST');
            if (currentSeason.current !== sid)
                return;
            setNotice({ kind: 'success', text: `Sync checked the selected CWL month. ${result.updated_accounts} account${result.updated_accounts === 1 ? '' : 's'} updated.` });
        }
        catch (cause) {
            if (currentSeason.current === sid && cause instanceof ApiError && [401, 403].includes(cause.status)) setData(null);
            if (currentSeason.current === sid)
                setSyncError(errorText(cause));
        }
        finally {
            if (currentSeason.current === sid)
                await load();
            setSyncBusy(false);
        }
    };
    const resetToSource = async (account: ParticipationAccount): Promise<ParticipationAccount> => {
        const sid = seasonId;
        try {
            const result = await api<{
                account: ParticipationAccount;
            }>(`/seasons/${encodeURIComponent(sid)}/participation/${encodeURIComponent(account.tag)}/reset-to-source`, 'POST', { revision: account.revision, publication_version: data?.publication_version ?? 0, roster_token: account.roster_token, source_checked_at: account.source_checked_at ?? null });
            if (currentSeason.current === sid) {
                setData(current => current ? { ...current, accounts: current.accounts.map(row => row.tag === account.tag ? result.account : row) } : current);
                setNotice({ kind: 'success', text: `${account.player_name} now uses synced results. Staff notes were kept.` });
            }
            return result.account;
        }
        catch (cause) {
            if (currentSeason.current === sid && cause instanceof ApiError && [401, 403].includes(cause.status)) setData(null);
            if (currentSeason.current === sid && cause instanceof ApiError && cause.status === 409) {
                setNotice({ kind: 'error', text: 'Source or roster changed. Latest records loaded; review before retrying.' });
                await load();
            }
            throw cause;
        }
    };
    const save = async (account: ParticipationAccount, revision: number, publicationVersion: number | null, sourceCheckedAt: string | null, attacks: number | null, stars: number | null, notes: string): Promise<ParticipationAccount> => {
        const sid = seasonId;
        try {
            const result = await api<{
                account: ParticipationAccount;
            }>(`/seasons/${encodeURIComponent(sid)}/participation/${encodeURIComponent(account.tag)}`, 'PATCH', { revision, publication_version: publicationVersion ?? 0, roster_token: account.roster_token, source_checked_at: sourceCheckedAt, attacks, stars, notes });
            if (currentSeason.current === sid) {
                setData(current => current ? { ...current, accounts: current.accounts.map(row => row.tag === account.tag ? result.account : row) } : current);
                setNotice({ kind: 'success', text: `${account.player_name} results saved.` });
            }
            return result.account;
        }
        catch (cause) {
            if (currentSeason.current === sid && cause instanceof ApiError && [401, 403].includes(cause.status)) setData(null);
            if (currentSeason.current === sid && cause instanceof ApiError && cause.status === 409) {
                setNotice({ kind: 'error', text: 'This record or assignment changed elsewhere. The latest records have been reloaded; review before saving again.' });
                await load();
            }
            throw cause;
        }
    };
    const archived = seasons.find(season => String(season.id) === seasonId)?.status.toLowerCase() === 'archived';
    const clans = [...new Map((data?.accounts || []).filter(account => account.assigned_clan_tag).map(account => [account.assigned_clan_tag!, account.assigned_clan_name || account.assigned_clan_tag!])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
    const visible = visibleParticipation(data?.accounts || [], { search, pool, clan, sort });
    const lastPage = Math.max(0, Math.ceil(visible.length / 20) - 1);
    const currentPage = Math.min(page, lastPage);
    useEffect(() => setPage(0), [search, pool, clan, sort, seasonId]);
    const visibleTags = new Set(visible.slice(currentPage * 20, (currentPage + 1) * 20).map(account => account.tag));
    const sorted = visibleParticipation(data?.accounts || [], { search: '', pool: 'all', clan: 'all', sort });
    return <div className="participation-workspace">
    <div className="page-head">
      <div>
      <p className="eyebrow">Staff tools</p>
      <h1>Results &amp; participation</h1>
      <p>Check attacks for this season’s signups, then review bonus winners.</p>
      </div>
      <label className="season-choice">Season<select value={seasonId} onChange={event => changeSeason(event.target.value)}>
      <option value="">Select a season</option>{seasons.map(season => <option key={season.id} value={String(season.id)}>{season.label}</option>)}</select>
      </label>
      </div>
    {!seasonId && <div className="card empty">
      <p>Select a season to view its participation records.</p>
      </div>}
    {error && <div className="notice error" role="alert">{error}<button onClick={() => void load()}>Retry</button>
      </div>}
    {notice && <div className={`notice ${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</div>}
    {loading && <p role="status">Loading results…</p>}
    {data && <>
      <section className="card participation-sync">
      <div className="card-heading">
      <div>
      <p className="eyebrow">Current signups &amp; working assignments</p>
      <h2>{data.accounts.length} signed-up accounts</h2>
      </div>
      <span className="badge">{syncStatusLabel(data.sync?.status)}</span>
      </div>
      <p>CWL month: <strong>{data.sync?.cycle || 'Not set — open sync settings below'}</strong> · Last checked: {data.sync?.last_checked_at ? dateText(data.sync.last_checked_at) : 'Not yet checked'}</p>
      <details>
      <summary>Sync settings &amp; check history</summary>
      <div className="participation-sync-fields">
      <label>CWL month<input type="month" value={syncDraft?.cycle || ''} disabled={archived || syncBusy} onChange={event => { setSyncDraft(current => ({ cycle: event.target.value, enabled: current?.enabled || false })); setSyncDirty(true); }}/>
      </label>
      <label className="participation-sync-toggle">
      <input type="checkbox" checked={syncDraft?.enabled || false} disabled={archived || syncBusy} onChange={event => { setSyncDraft(current => ({ cycle: current?.cycle || '', enabled: event.target.checked })); setSyncDirty(true); }}/>
      <span>Check automatically every 15 minutes</span>
      </label>
      </div>
      <div className="participation-sync-meta">
      <small>Selected source: {data.sync?.cycle_source === 'manage_binding' ? 'Manage CWL settings' : data.sync?.cycle_source === 'settings' ? 'Staff setting' : 'None'}</small>
      <small>Last checked: {data.sync?.last_checked_at ? dateText(data.sync.last_checked_at) : 'Never'}</small>
      <small>Last successful check: {data.sync?.last_success_at ? dateText(data.sync.last_success_at) : 'Never'}</small>
      </div>
      </details>{data.sync?.warning && <p className="inline-reason" role="alert">{data.sync.warning}</p>}{syncError && <p className="inline-reason" role="alert">{syncError}</p>}{archived && <p className="small">Archived seasons are read-only.</p>}<div className="participation-sync-actions">
      <button disabled={loading || syncBusy} onClick={() => void load()}>Refresh list</button>{syncDirty && <button disabled={archived || syncBusy || !syncDirty || !validCwlCycle(syncDraft?.cycle || '')} onClick={() => void saveSyncSettings()}>{syncBusy ? 'Working…' : 'Save sync settings'}</button>}<button className="primary" disabled={archived || syncBusy || syncDirty || !data.sync?.cycle} onClick={() => void syncNow()}>{syncBusy ? 'Checking…' : 'Refresh Clash results'}</button>
      </div>{syncDirty && <p className="small">Save the selected month and automatic setting before syncing.</p>}</section>
      {archived && <div className="notice">This season is archived. Results are read-only.</div>}
      <CwlPoolTabs value={pool} onChange={next => { setPool(next); setClan('all'); }}/>
      {data.accounts.length > 0 ? <>
      <div className="card participation-filter">
      <label>Search account or clan<input value={search} onChange={event => setSearch(event.target.value)} placeholder="Name, tag, or clan"/>
      </label>
      <label>Hosting clan<select value={clan} onChange={event => setClan(event.target.value)}>
      <option value="all">All hosting clans</option>{clans.map(([tag, name]) => <option key={tag} value={tag}>{name} · {tag}</option>)}</select>
      </label>
      <label>Sort<select value={sort} onChange={event => setSort(event.target.value as ParticipationSort)}>
      <option value="name">Name A–Z</option>
      <option value="attacks-desc">Attacks high to low</option>
      <option value="attacks-asc">Attacks low to high</option>
      <option value="stars-desc">Stars high to low</option>
      <option value="stars-asc">Stars low to high</option>
      <option value="th-desc">Town Hall high to low</option>
      <option value="th-asc">Town Hall low to high</option>
      </select>
      </label>
      </div>
      <p className="small">Showing {visible.length ? currentPage * 20 + 1 : 0}–{Math.min((currentPage + 1) * 20, visible.length)} of {visible.length} matching accounts · Unknown values appear last.</p>
      <div className="participation-grid">{sorted.map(account => <div key={`${seasonId}:${account.tag}`} hidden={!visibleTags.has(account.tag)}>
      <ParticipationRecord account={account} publicationVersion={data.publication_version} archived={!!archived || syncBusy || loading} onSave={save} onReset={resetToSource} onDirty={onDirty}/>
      </div>)}</div>{!visible.length && <div className="card empty">
      <p>No accounts match these filters.</p>
      </div>}</> : <div className="card empty">
      <h2>No participation accounts yet</h2>
      <p>Refresh Clash results for your assigned signup accounts. No roster publication is required to sync attacks.</p>
      </div>}
      <ParticipationHistory key={seasonId} seasonId={seasonId}/>
      {lastPage > 0 && <nav className="roster-pagination" aria-label="Participation pages">
      <button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button>
      <span>Page {currentPage + 1} of {lastPage + 1}</span>
      <button disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>Next</button>
      </nav>}
    </>}
  </div>;
}
