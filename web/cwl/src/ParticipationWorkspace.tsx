import './ParticipationWorkspace.css';
import CwlPoolTabs, { useCwlPool } from './CwlPoolTabs';
import ParticipationRecord from './ParticipationRecord';
import ParticipationHistory from './ParticipationHistory';
import useUnsavedWork from './useUnsavedWork';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, type Season } from './api';
import {
  validCwlCycle, visibleParticipation, syncStatusLabel,
  type ParticipationAccount, type ParticipationData, type ParticipationSort, type ParticipationSync,
} from './participation';

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
  const [notice, setNotice] = useState<{ text: string; kind: 'success' | 'error' } | null>(null);
  const [dirtyTags, setDirtyTags] = useState<Set<string>>(new Set());
  const [activeEditorTag, setActiveEditorTag] = useState<string | null>(null);
  const [syncDraft, setSyncDraft] = useState<{ cycle: string; enabled: boolean; expected_updated_at: string | null } | null>(null);
  const [syncDirty, setSyncDirty] = useState(false);
  const syncDirtyRef = useRef(false);
  syncDirtyRef.current = syncDirty;
  const [syncBusy, setSyncBusy] = useState(false);
  const [syncError, setSyncError] = useState('');
  const [page, setPage] = useState(0);
  const [recordEpoch, setRecordEpoch] = useState(0);
  const [search, setSearch] = useState('');
  const [pool, setPool] = useCwlPool();
  const [clan, setClan] = useState('all');
  const [sort, setSort] = useState<ParticipationSort>('name');
  const requestId = useRef(0);
  const currentSeason = useRef(seasonId);
  currentSeason.current = seasonId;
  const archived = seasons.find(season => String(season.id) === seasonId)?.status.toLowerCase() === 'archived';
  const editing = activeEditorTag !== null;
  const controlsLocked = editing || syncBusy || loading;
  const writesLocked = controlsLocked || !!error;
  useUnsavedWork(dirtyTags.size > 0 || syncDirty || syncBusy, reportDirty);

  const onDirty = useCallback((tag: string, dirty: boolean) => setDirtyTags(current => {
    if (current.has(tag) === dirty) return current;
    const next = new Set(current);
    if (dirty) next.add(tag);
    else next.delete(tag);
    return next;
  }), []);
  const clearProtected = () => {
    setData(null);
    setSyncDraft(null);
    setNotice(null);
    setActiveEditorTag(null);
    setDirtyTags(new Set());
  };
  const load = useCallback(async () => {
    if (!seasonId) return;
    const sid = seasonId;
    const id = ++requestId.current;
    setLoading(true);
    setError('');
    try {
      const result = await api<ParticipationData>(`/seasons/${encodeURIComponent(sid)}/participation`);
      if (id !== requestId.current || currentSeason.current !== sid) return;
      setData(result);
      if (result.sync && !syncDirtyRef.current) setSyncDraft({ cycle: result.sync.cycle || '', enabled: result.sync.enabled, expected_updated_at: result.sync.updated_at ?? null });
    } catch (cause) {
      if (id !== requestId.current || currentSeason.current !== sid) return;
      setError(errorText(cause));
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) clearProtected();
    } finally {
      if (id === requestId.current && currentSeason.current === sid) setLoading(false);
    }
  }, [seasonId]);
  useEffect(() => {
    requestId.current += 1;
    clearProtected();
    setError('');
    setSyncDirty(false);
    setSyncError('');
    setSearch('');
    setClan('all');
    setSort('name');
    if (seasonId) void load();
    return () => { requestId.current += 1; };
  }, [seasonId, load]);
  useEffect(() => setPage(0), [search, pool, clan, sort, seasonId]);

  const changeSeason = (id: string) => {
    if (controlsLocked) return;
    if ((dirtyTags.size || syncDirty) && !window.confirm(`Discard unsaved participation changes and open another season?`)) return;
    setDirtyTags(new Set());
    onSeasonChange(id);
  };
  const refreshList = () => {
    if (controlsLocked) return;
    if ((dirtyTags.size || syncDirty) && !window.confirm('Discard unsaved participation changes and refresh?')) return;
    if (dirtyTags.size) {
      setDirtyTags(new Set());
      setRecordEpoch(current => current + 1);
    }
    setSyncDirty(false);
    syncDirtyRef.current = false;
    setSyncError('');
    void load();
  };
  const saveSyncSettings = async () => {
    if (!seasonId || !syncDraft || syncBusy || editing || archived || error || !validCwlCycle(syncDraft.cycle)) return;
    const sid = seasonId;
    const cycleChanged = syncDraft.cycle !== data?.sync?.cycle;
    if (cycleChanged && dirtyTags.size && !window.confirm(`Changing the CWL month will discard unsaved result edits for ${dirtyTags.size} account${dirtyTags.size === 1 ? '' : 's'}. Continue?`)) return;
    setSyncBusy(true);
    setSyncError('');
    try {
      const result = await api<{ sync: ParticipationSync }>(`/seasons/${encodeURIComponent(sid)}/participation/sync-settings`, 'POST', syncDraft);
      if (currentSeason.current !== sid) return;
      setSyncDirty(false);
      syncDirtyRef.current = false;
      if (cycleChanged) { setData(null); setDirtyTags(new Set()); setRecordEpoch(current => current + 1); }
      else setData(current => current ? { ...current, sync: result.sync } : current);
      await load();
      if (currentSeason.current === sid) setNotice({ kind: 'success', text: result.sync.enabled ? 'Automatic CWL capture enabled.' : 'Automatic CWL capture disabled. You can still check manually.' });
    } catch (cause) {
      if (currentSeason.current === sid) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) clearProtected();
        setSyncError(errorText(cause));
        if (cause instanceof ApiError && cause.status === 409) await load();
      }
    } finally { setSyncBusy(false); }
  };
  const syncNow = async () => {
    if (!seasonId || syncBusy || editing || dirtyTags.size || archived || error || !data?.sync?.cycle || syncDirty) return;
    const sid = seasonId;
    setSyncBusy(true);
    setSyncError('');
    try {
      const result = await api<{ sync: ParticipationSync; updated_accounts: number }>(`/seasons/${encodeURIComponent(sid)}/participation/sync`, 'POST');
      if (currentSeason.current !== sid) return;
      setNotice({ kind: 'success', text: `Clash checked this CWL month. ${result.updated_accounts} account${result.updated_accounts === 1 ? '' : 's'} updated.` });
    } catch (cause) {
      if (currentSeason.current === sid) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) clearProtected();
        setSyncError(errorText(cause));
      }
    } finally {
      if (currentSeason.current === sid) await load();
      setSyncBusy(false);
    }
  };
  const resetToSource = async (account: ParticipationAccount): Promise<ParticipationAccount> => {
    const sid = seasonId;
    if (error) throw new Error('Refresh the results list before editing.');
    try {
      const result = await api<{ account: ParticipationAccount }>(`/seasons/${encodeURIComponent(sid)}/participation/${encodeURIComponent(account.tag)}/reset-to-source`, 'POST', {
        revision: account.revision, publication_version: data?.publication_version ?? 0,
        roster_token: account.roster_token, source_checked_at: account.source_checked_at ?? null,
      });
      if (currentSeason.current === sid) {
        setData(current => current ? { ...current, accounts: current.accounts.map(row => row.tag === account.tag ? result.account : row) } : current);
        setNotice({ kind: 'success', text: `${account.player_name} now uses synced values. Staff notes were kept.` });
      }
      return result.account;
    } catch (cause) {
      if (currentSeason.current === sid) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) clearProtected();
        if (cause instanceof ApiError && cause.status === 409) {
          setNotice({ kind: 'error', text: 'Source or roster changed. Latest records loaded; review before retrying.' });
          await load();
        }
      }
      throw cause;
    }
  };
  const save = async (account: ParticipationAccount, revision: number, publicationVersion: number | null,
    sourceCheckedAt: string | null, attacks: number | null, stars: number | null, notes: string): Promise<ParticipationAccount> => {
    const sid = seasonId;
    if (error) throw new Error('Refresh the results list before editing.');
    try {
      const result = await api<{ account: ParticipationAccount }>(`/seasons/${encodeURIComponent(sid)}/participation/${encodeURIComponent(account.tag)}`, 'PATCH', {
        revision, publication_version: publicationVersion ?? 0, roster_token: account.roster_token,
        source_checked_at: sourceCheckedAt, attacks, stars, notes,
      });
      if (currentSeason.current === sid) {
        setData(current => current ? { ...current, accounts: current.accounts.map(row => row.tag === account.tag ? result.account : row) } : current);
        setNotice({ kind: 'success', text: `${account.player_name} results saved.` });
      }
      return result.account;
    } catch (cause) {
      if (currentSeason.current === sid) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) clearProtected();
        if (cause instanceof ApiError && cause.status === 409) {
          setNotice({ kind: 'error', text: 'This record or assignment changed elsewhere. Latest records loaded; review before saving again.' });
          await load();
        }
      }
      throw cause;
    }
  };

  const clans = [...new Map((data?.accounts || []).filter(account => account.assigned_clan_tag)
    .map(account => [account.assigned_clan_tag!, account.assigned_clan_name || account.assigned_clan_tag!])).entries()]
    .sort((left, right) => left[1].localeCompare(right[1]));
  const visible = visibleParticipation(data?.accounts || [], { search, pool, clan, sort });
  const lastPage = Math.max(0, Math.ceil(visible.length / 20) - 1);
  const currentPage = Math.min(page, lastPage);
  const visibleTags = new Set(visible.slice(currentPage * 20, (currentPage + 1) * 20).map(account => account.tag));
  // Keep all records mounted while filtering so a failed save never destroys a draft.
  const sorted = visibleParticipation(data?.accounts || [], { search: '', pool: 'all', clan: 'all', sort });
  const incomplete = data?.accounts.filter(account => !account.source_complete || ['stale', 'unavailable', 'never'].includes(account.source_status || '')).length || 0;

  return <div className="participation-workspace">
    <div className="page-head participation-page-head">
      <div><p className="eyebrow">CWL · Results</p><h1>Results &amp; participation</h1><p>Check CWL attacks and stars for current signups.</p></div>
      <label className="season-choice">Season<select value={seasonId} disabled={controlsLocked} onChange={event => changeSeason(event.target.value)}>
        <option value="">Select a season</option>{seasons.map(season => <option key={season.id} value={String(season.id)}>{season.label}</option>)}</select></label>
    </div>
    {!seasonId && <p>Select a season to view participation records.</p>}
    {error && <div className="notice error" role="alert">Results could not be refreshed. {data && 'Existing values may be out of date; edits are paused. '}{error}<button type="button" disabled={loading || editing} onClick={refreshList}>Retry</button></div>}
    {notice && <div className={`notice ${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</div>}
    {loading && !data && <p role="status">Loading results…</p>}
    {data && <>
      <section className="participation-capture" aria-label="CWL capture status">
        <div className="participation-capture-main">
          <div><strong>{data.sync?.enabled ? 'Automatic capture on' : 'Automatic capture off'}</strong>
            <span>{data.sync?.cycle || 'CWL month not set'} · {syncStatusLabel(data.sync?.status)} · Last checked {data.sync?.last_checked_at ? dateText(data.sync.last_checked_at) : 'never'}</span></div>
          <div className="participation-capture-actions">
            <button type="button" disabled={writesLocked || !!dirtyTags.size || syncDirty || archived || !data.sync?.cycle} onClick={() => void syncNow()}>Check Clash now</button>
            <button type="button" disabled={controlsLocked} onClick={refreshList}>Refresh list</button>
          </div>
        </div>
        {!data.sync?.enabled && <p className="participation-capture-warning" role="status">Automatic CWL capture is off. Enable it in Capture settings to retain current results.</p>}
        {!!incomplete && <p className="participation-capture-warning" role="status">{incomplete} account{incomplete === 1 ? '' : 's'} with incomplete, stale or unavailable source results.</p>}
        {data.sync?.warning && <p className="participation-capture-warning" role="alert">{data.sync.warning}</p>}
        {syncError && <p className="participation-capture-warning" role="alert">{syncError}</p>}
        {!data.sync?.cycle && <p className="participation-capture-warning">Set the CWL month in Capture settings before checking Clash.</p>}
        <details className="participation-capture-settings">
          <summary>Capture settings and last check{syncDirty ? ' · Unsaved' : ''}</summary>
          <div className="participation-sync-fields">
            <label>CWL month<input type="month" value={syncDraft?.cycle || ''} disabled={archived || writesLocked} onChange={event => { setSyncDraft(current => ({ cycle: event.target.value, enabled: current?.enabled || false, expected_updated_at: current?.expected_updated_at ?? null })); setSyncDirty(true); }} /></label>
            <label className="participation-sync-toggle"><input type="checkbox" checked={syncDraft?.enabled || false} disabled={archived || writesLocked} onChange={event => { setSyncDraft(current => ({ cycle: current?.cycle || '', enabled: event.target.checked, expected_updated_at: current?.expected_updated_at ?? null })); setSyncDirty(true); }} />Check automatically every 15 minutes</label>
          </div>
          <div className="participation-sync-meta"><small>Month source: {data.sync?.cycle_source === 'manage_binding' ? 'Manage CWL settings' : data.sync?.cycle_source === 'settings' ? 'Staff setting' : 'None'}</small>
            <small>Last success: {data.sync?.last_success_at ? dateText(data.sync.last_success_at) : 'Never'}</small></div>
          {syncDirty && <div className="participation-settings-actions"><button type="button" disabled={archived || writesLocked || !validCwlCycle(syncDraft?.cycle || '')} onClick={() => void saveSyncSettings()}>Save capture settings</button>
            <button type="button" disabled={controlsLocked} onClick={() => { setSyncDraft({ cycle: data.sync?.cycle || '', enabled: !!data.sync?.enabled, expected_updated_at: data.sync?.updated_at ?? null }); setSyncDirty(false); setSyncError(''); }}>Discard changes</button></div>}
        </details>
      </section>
      {archived && <div className="notice">Archived season · Results are read only.</div>}
      <CwlPoolTabs value={pool} disabled={controlsLocked} onChange={next => { setPool(next); setClan('all'); }} />
      <div className="participation-toolbar">
        <label>Find a player<input type="search" value={search} disabled={controlsLocked} onChange={event => setSearch(event.target.value)} placeholder="Name, tag or clan" /></label>
        <label>Hosting clan<select value={clan} disabled={controlsLocked} onChange={event => setClan(event.target.value)}><option value="all">All hosting clans</option>{clans.map(([tag, name]) => <option key={tag} value={tag}>{name} · {tag}</option>)}</select></label>
        <label>Sort<select value={sort} disabled={controlsLocked} onChange={event => setSort(event.target.value as ParticipationSort)}>
          <option value="name">Name A–Z</option><option value="attacks-desc">Attacks high to low</option><option value="attacks-asc">Attacks low to high</option>
          <option value="stars-desc">Stars high to low</option><option value="stars-asc">Stars low to high</option>
          <option value="th-desc">Town Hall high to low</option><option value="th-asc">Town Hall low to high</option>
        </select></label>
      </div>
      <div className="participation-list-heading"><strong>Players</strong><span>{visible.length} matching · {data.accounts.length} current signups</span></div>
      {data.accounts.length ? <>
        <div className="participation-list" role="list">
          {sorted.map(account => <div role="listitem" key={`${seasonId}:${recordEpoch}:${account.tag}`} hidden={!visibleTags.has(account.tag)}>
            <ParticipationRecord account={account} publicationVersion={data.publication_version} readonly={!!archived} locked={writesLocked}
              open={activeEditorTag === account.tag} onOpen={() => setActiveEditorTag(account.tag)} onClose={() => setActiveEditorTag(current => current === account.tag ? null : current)}
              onSave={save} onReset={resetToSource} onDirty={onDirty} />
          </div>)}
        </div>
        {!visible.length && <p className="participation-empty">No players match these filters.</p>}
      </> : <p className="participation-empty">No current signup accounts yet. Working roster assignments can sync without publication.</p>}
      {lastPage > 0 && <nav className="roster-pagination" aria-label="Participation pages">
        <button type="button" disabled={controlsLocked || currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button>
        <span>Page {currentPage + 1} of {lastPage + 1}</span>
        <button type="button" disabled={controlsLocked || currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>Next</button>
      </nav>}
      <ParticipationHistory key={seasonId} seasonId={seasonId} onAccessDenied={cause => { clearProtected(); setError(errorText(cause)); }} />
    </>}
  </div>;
}
