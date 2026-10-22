import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useDashboardPermission } from './DashboardPermissions';
import { api, ApiError, type Season } from './api';
import CwlPoolTabs, { useCwlPool } from './CwlPoolTabs';
import useUnsavedWork from './useUnsavedWork';
import BonusAnnouncement from './BonusAnnouncement';
import BonusCandidateReview, { LAZY_FLAGS } from './BonusCandidateReview';
import { attacksText, bonusCandidateStatus, canSaveBonusDraw, type BonusListMode, type RaffleAccount, type RaffleData, type RafflePreview } from './bonusRaffle';
import './BonusWorkspace.css';

type Props = {
  seasonId: string;
  seasons: Season[];
  onDirty?: (dirty: boolean) => void;
  onSeasonChange: (id: string) => void;
};

type Role = { id: string; name: string };
type PlayerLookup = { account: { tag: string; name: string; town_hall: number; current_clan_name?: string | null } };

function errorText(cause: unknown) {
  return cause instanceof Error ? cause.message : 'The action could not be completed. Refresh to check its saved status.';
}

function AccountList({ accounts, onReview, busy, searchable = false, mode = 'candidates' }: {
  accounts: RaffleAccount[];
  onReview?: (account: RaffleAccount, opener: HTMLButtonElement) => void;
  busy?: boolean;
  searchable?: boolean;
  mode?: BonusListMode;
}) {
  const [query, setQuery] = useState('');
  const [visibleCount, setVisibleCount] = useState(20);
  const matching = useMemo(() => accounts.filter(account =>
    `${account.player_name} ${account.tag}`.toLowerCase().includes(query.trim().toLowerCase())
  ), [accounts, query]);

  return <div className="bonus-account-results">
    {searchable && <label className="bonus-account-search">Find an account
      <input type="search" value={query} onChange={event => { setQuery(event.target.value); setVisibleCount(20); }} placeholder="Player name or tag" />
    </label>}
    <ul className="bonus-account-list">
      {matching.slice(0, searchable ? visibleCount : matching.length).map(account => <li key={account.tag}>
        <div className="bonus-account-identity">
          <strong>{account.player_name}</strong>
          <small>{account.tag}{account.manual_candidate ? ' · Added by staff' : ''}</small>
        </div>
        <div className="bonus-account-outcome">
          <strong>{attacksText(account)}{account.stars !== null ? ` · ${account.stars} stars` : ''}</strong>
          {(bonusCandidateStatus(account, mode) || account.multiplier === 2) && <small>{bonusCandidateStatus(account, mode)}{bonusCandidateStatus(account, mode) && account.multiplier === 2 ? ' · ' : ''}{account.multiplier === 2 ? '2× ticket weight' : ''}</small>}
          {!!account.bonus_review?.flags.length && <small>{account.bonus_review.flags.map(flag => LAZY_FLAGS.find(item => item.id === flag)?.label || flag).join(' · ')}</small>}
        </div>
        {onReview && <button type="button" className="bonus-quiet-action" disabled={busy} onClick={event => onReview(account, event.currentTarget)}>Review<span className="sr-only"> {account.player_name}</span></button>}
      </li>)}
    </ul>
    {searchable && matching.length > visibleCount && <button type="button" className="bonus-show-more" onClick={() => setVisibleCount(count => count + 20)}>Show 20 more · {matching.length - visibleCount} remaining</button>}
    {!matching.length && <p className="bonus-empty">{query ? 'No accounts match this search.' : 'No accounts in this group.'}</p>}
  </div>;
}

export default function BonusWorkspace({ seasonId, seasons, onDirty, onSeasonChange }: Props) {
  const canManage = useDashboardPermission('cwl_bonuses');
  const [pool, setPool] = useCwlPool();
  const [data, setData] = useState<RaffleData | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [clanTag, setClanTag] = useState('');
  const [minimum, setMinimum] = useState('');
  const [slots, setSlots] = useState('');
  const [manualCount, setManualCount] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [preview, setPreview] = useState<RafflePreview | null>(null);
  const [reviewTag, setReviewTag] = useState('');
  const [reviewDirty, setReviewDirty] = useState(false);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateTag, setCandidateTag] = useState('');
  const [candidateReason, setCandidateReason] = useState('');
  const [candidateLookup, setCandidateLookup] = useState<PlayerLookup | null>(null);
  const [lookingUp, setLookingUp] = useState(false);
  const [roleId, setRoleId] = useState('');
  const [roles, setRoles] = useState<Role[]>([]);
  const [rolesError, setRolesError] = useState('');
  const [rolesLoading, setRolesLoading] = useState(false);
  const [roleSearch, setRoleSearch] = useState('');
  const reviewOpener = useRef<HTMLButtonElement | null>(null);
  const addOpener = useRef<HTMLButtonElement | null>(null);
  const candidateHeading = useRef<HTMLHeadingElement | null>(null);
  const generation = useRef(0);
  const lookupGeneration = useRef(0);
  const working = useRef(false);
  const activeSeason = useRef(seasonId);
  activeSeason.current = seasonId;
  const path = `/seasons/${encodeURIComponent(seasonId)}/bonus-raffle`;
  const archived = data?.season_status !== 'draft';
  const policyDirty = pool === 'main' && !!data && minimum !== String(data.policies.main ?? '');
  const roleDirty = pool === 'lazy' && !!data && roleId !== (data.lazy_settings?.representative_role_id || '769130325460254740');
  const formDirty = reviewDirty || (candidateOpen && !!(candidateTag || candidateReason)) || roleDirty;
  const unsaved = policyDirty || formDirty || (manualCount && !!slots && !data?.draws.some(draw =>
    draw.pool === pool && draw.clan_tag === clanTag && draw.cycle === data.cycle && !draw.cancelled_at
  ));
  useUnsavedWork(unsaved || busy || lookingUp || !!cancelReason, onDirty);

  const currentClans = data?.clans.filter(clan => data.accounts.some(account =>
    account.pool === pool && account.assigned_clan_tag === clan.tag
  )) || [];
  const clans = pool === 'lazy' ? [...(data?.lazy_hosts || []), ...currentClans.filter(clan => !data?.lazy_hosts?.some(host => host.tag === clan.tag))] : [...currentClans];
  for (const saved of data?.draws || []) {
    if (saved.pool === pool && saved.cycle === data?.cycle && !saved.cancelled_at && !clans.some(clan => clan.tag === saved.clan_tag)) {
      clans.push({ tag: saved.clan_tag, name: `${saved.snapshot.clan_name} · Saved draw`, slots: saved.snapshot.slots });
    }
  }
  const selectedClan = clans.find(clan => clan.tag === clanTag);
  const draw = data?.draws.find(item => item.pool === pool && item.clan_tag === clanTag && item.cycle === data.cycle && !item.cancelled_at);
  const allowance = data?.allowances?.[clanTag];
  const requestedSlots = manualCount ? Number(slots) : null;
  const countReady = manualCount ? /^\d+$/.test(slots) && Number(slots) >= 1 && Number(slots) <= 50 : allowance?.status === 'ready';
  const clanAccounts = data?.accounts.filter(account => account.pool === pool && account.assigned_clan_tag === clanTag) || [];
  const reviewAccount = clanAccounts.find(account => account.tag === reviewTag);
  const stage = draw?.approved_at ? 3 : draw ? 2 : preview ? 1 : 0;

  const resetContext = (source = data, nextPool = pool) => {
    lookupGeneration.current += 1;
    setLookingUp(false);
    setMinimum(String(source?.policies[nextPool] ?? ''));
    setRoleId(source?.lazy_settings?.representative_role_id || '769130325460254740');
    setManualCount(false);
    setPreview(null);
    setSlots('');
    setCancelReason('');
    setReviewTag('');
    setReviewDirty(false);
    setCandidateOpen(false);
    setCandidateTag('');
    setCandidateReason('');
    setCandidateLookup(null);
    setNotice('');
  };

  const load = useCallback(async () => {
    if (!seasonId || working.current) return;
    working.current = true;
    const request = ++generation.current;
    setBusy(true);
    setError('');
    try {
      const result = await api<RaffleData>(path);
      if (request !== generation.current) return;
      setData(result);
      setPreview(null);
      setRoleId(result.lazy_settings?.representative_role_id || '769130325460254740');
    } catch (cause) {
      if (request !== generation.current) return;
      setData(null);
      setError(errorText(cause));
    } finally {
      if (request === generation.current) { working.current = false; setBusy(false); }
    }
  }, [path, seasonId]);

  useEffect(() => {
    generation.current += 1;
    working.current = false;
    setData(null);
    setClanTag('');
    setError('');
    resetContext(null);
    void load();
    return () => { generation.current += 1; };
  }, [load]);
  useEffect(() => { if (data) setMinimum(String(data.policies[pool] ?? '')); }, [data, pool]);
  useEffect(() => { if (!clans.some(clan => clan.tag === clanTag)) setClanTag(clans[0]?.tag || ''); }, [data, pool, clanTag]);

  const mutate = async (suffix: string, body: unknown, success: string, method = 'POST') => {
    if (working.current || archived) return false;
    working.current = true;
    setBusy(true);
    setError('');
    setNotice('');
    const request = ++generation.current;
    const sid = seasonId;
    try {
      const result = await api<RaffleData>(path + suffix, method, body);
      if (request !== generation.current || activeSeason.current !== sid) return false;
      setData(result);
      setPreview(null);
      setCancelReason('');
      setNotice(success);
      return true;
    } catch (cause) {
      if (request !== generation.current) return false;
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) setData(null);
      setPreview(null);
      setError(errorText(cause));
      return false;
    } finally {
      if (request === generation.current) { working.current = false; setBusy(false); }
    }
  };
  const canDiscard = () => (!unsaved && !cancelReason) || window.confirm('Discard unsaved bonus edits?');
  const canLeaveEditor = () => (!reviewDirty && !(candidateOpen && (candidateTag || candidateReason))) || window.confirm('Discard unsaved candidate edits?');
  const refresh = () => { if (canDiscard()) { resetContext(); void load(); } };
  const review = async () => {
    if (working.current || !selectedClan || policyDirty || roleDirty || archived) return;
    working.current = true;
    setBusy(true);
    setError('');
    setPreview(null);
    const request = ++generation.current;
    try {
      const result = await api<RafflePreview>(path + '/preview', 'POST', { pool, clan_tag: clanTag, slots: requestedSlots });
      if (request === generation.current) setPreview(result);
    } catch (cause) {
      if (request === generation.current) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) setData(null);
        setError(errorText(cause));
      }
    } finally {
      if (request === generation.current) { working.current = false; setBusy(false); }
    }
  };
  const lookupCandidate = async () => {
    if (!candidateTag.trim() || lookingUp) return;
    const lookup = ++lookupGeneration.current;
    const lookupSeason = seasonId;
    setLookingUp(true);
    setCandidateLookup(null);
    setError('');
    try {
      const result = await api<PlayerLookup>(`/seasons/${encodeURIComponent(seasonId)}/staff-signups/player?tag=${encodeURIComponent(candidateTag.trim())}`);
      if (lookup === lookupGeneration.current && lookupSeason === activeSeason.current) setCandidateLookup(result);
    } catch (cause) {
      if (lookup === lookupGeneration.current && lookupSeason === activeSeason.current) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) setData(null);
        setError(errorText(cause));
      }
    } finally { if (lookup === lookupGeneration.current) setLookingUp(false); }
  };
  const closeReview = () => {
    setReviewTag('');
    setReviewDirty(false);
    const opener = reviewOpener.current;
    requestAnimationFrame(() => (opener?.isConnected ? opener : candidateHeading.current)?.focus({ preventScroll: true }));
  };
  const closeCandidate = () => {
    setCandidateOpen(false);
    setCandidateTag('');
    setCandidateReason('');
    setCandidateLookup(null);
    requestAnimationFrame(() => addOpener.current?.focus({ preventScroll: true }));
  };
  const loadRoles = async () => {
    if (roles.length || rolesLoading) return;
    setRolesLoading(true);
    setRolesError('');
    try {
      const result = await api<{ roles: Role[] }>('/announcement-roles');
      setRoles(result.roles);
    } catch (cause) { setRolesError(errorText(cause)); }
    finally { setRolesLoading(false); }
  };

  return <div className="bonus-workspace">
    <div className="page-head bonus-page-head">
      <div><p className="eyebrow">CWL · Results &amp; bonuses</p><h1>Bonus winners</h1></div>
      <label className="season-choice">Season<select value={seasonId} disabled={busy || lookingUp} onChange={event => {
        if (canDiscard()) onSeasonChange(event.target.value);
      }}><option value="">Select a season</option>{seasons.map(season => <option key={season.id} value={season.id}>{season.label}</option>)}</select></label>
    </div>
    <CwlPoolTabs value={pool} disabled={busy || lookingUp} onChange={next => {
      if (canDiscard()) { setPool(next); resetContext(data, next); }
    }} />
    {error && <div className="notice error" role="alert">{error} <button type="button" disabled={busy} onClick={refresh}>Refresh saved status</button></div>}
    {notice && <p role="status">{notice}</p>}
    {busy && <p role="status">Working…</p>}
    {!seasonId && <p>Select a season to begin.</p>}
    {data && <>
      <div className="bonus-context"><strong>{data.cycle || 'CWL month not set'}</strong>
        <span>{data.sync.last_checked_at ? `Clash checked ${new Date(data.sync.last_checked_at).toLocaleString()}` : 'Clash not checked yet'}</span>
        <button type="button" disabled={busy || lookingUp} onClick={refresh}>Refresh</button></div>
      {archived && <p className="notice">Archived season · Read only</p>}
      {!data.cycle && <p className="notice">Choose this season’s CWL month in Results &amp; participation first.</p>}
      {!data.sync.enabled && <p className="notice error" role="alert"><span>Automatic CWL capture is off. Enable checks in <a href={`/cwl/results?season=${encodeURIComponent(seasonId)}`} onClick={event => { if (!canDiscard()) event.preventDefault(); }}>Participation</a> to retain results.</span></p>}
      {data.sync.warning && <p className="notice" role="status">{data.sync.warning}</p>}
      <ol className="bonus-steps" aria-label="Bonus progress">{['Eligibility', 'Saved draw', 'Approval', 'Announcement'].map((step, index) =>
        <li key={step} aria-current={stage === index ? 'step' : undefined}><span>{index + 1}</span>{step}</li>)}</ol>

      <div className="bonus-controls">
        <label>Hosting clan<select value={clanTag} disabled={busy || lookingUp} onChange={event => {
          if (canDiscard()) { setClanTag(event.target.value); resetContext(); }
        }}>
          {!clans.length && <option value="">No assigned hosting clans</option>}
          {clans.map(clan => <option key={clan.tag} value={clan.tag}>{clan.name} · {clan.tag}</option>)}
        </select></label>
        <button type="button" disabled={!canManage || busy || lookingUp || archived || policyDirty || roleDirty || reviewDirty || candidateOpen || !data.cycle} onClick={() => void mutate('/refresh-results', {}, 'Clash results refreshed. Review incomplete data before drawing.')}>Refresh attacks from Clash</button>
      </div>
      {!clans.length && <p>No current signups are assigned to a hosting clan in this CWL pool.</p>}

      {selectedClan && !draw && <section className="bonus-flow">
        <div className="bonus-section-heading"><h2>{selectedClan.name}</h2></div>
        <div className="bonus-stats" role="status">
          <div><strong>{manualCount && countReady ? Number(slots) : allowance?.status === 'ready' ? allowance.total : '—'}</strong><span>Total bonus allowance{manualCount && countReady ? ' · staff count' : ''}</span></div>
          <div><strong>{clanAccounts.length}</strong><span>Current candidates</span></div>
          <div><strong>{preview?.eligible.length ?? (pool === 'lazy' ? clanAccounts.filter(account => !account.exclusion).length : '—')}</strong><span>{preview ? 'Verified eligible' : pool === 'lazy' ? 'Meets rules now' : 'Qualifying'}</span></div>
        </div>
        <p className="bonus-support">{allowance?.reason || 'Refresh Clash results to check the allowance.'}</p>
        <details className="bonus-secondary"><summary>Bonus count and source</summary>
          <p>{allowance?.league || 'League unknown'}{allowance?.team_size ? ` · ${allowance.team_size} vs ${allowance.team_size}` : ''} · {allowance?.completed_wars ?? 0}/{allowance?.rounds ?? '?'} wars complete{allowance?.base != null ? ` · ${allowance.base} base + ${allowance.wins} wins${allowance.status === 'ready' ? ` = ${allowance.total}` : ''}` : ''}</p>
          <label className="bonus-check"><input type="checkbox" checked={manualCount} disabled={!canManage || busy || archived} onChange={event => { setManualCount(event.target.checked); setPreview(null); }} />Use the total shown in Clash</label>
          {manualCount && <label>Total bonuses shown in Clash<input type="number" min="1" max="50" step="1" value={slots} disabled={!canManage || busy || archived} onChange={event => { setSlots(event.target.value); setPreview(null); }} /></label>}
          {manualCount && <p className="bonus-caution">Staff-confirmed count; not API-verified.</p>}
        </details>

        {pool === 'main' ? <div className="bonus-policy">
          <label>Minimum attacks<input type="number" min="0" max="7" step="1" value={minimum} disabled={!canManage || busy || archived} onChange={event => { setMinimum(event.target.value); setPreview(null); }} /></label>
          <button type="button" disabled={!canManage || busy || archived || reviewDirty || candidateOpen || !policyDirty || !/^\d+$/.test(minimum) || Number(minimum) > 7} onClick={() => void mutate('/policy', { pool, minimum: Number(minimum), revision: data.revision }, 'Minimum attacks saved. Earlier draws stay unchanged.', 'PATCH')}>Save minimum</button>
        </div> : <>
          <div className="bonus-candidates-heading"><h3 ref={candidateHeading} tabIndex={-1}>Candidate review</h3><button ref={addOpener} type="button" disabled={!canManage || busy || archived} onClick={() => { setCandidateOpen(current => !current); setCandidateLookup(null); }}>Add player by tag</button></div>
          {candidateOpen && <section className="bonus-add-candidate" aria-label="Add bonus candidate">
            <p>Add an account directly to this clan’s candidate pool. This does not change its signup or roster placement.</p>
            <div className="bonus-lookup"><label>Player tag<input value={candidateTag} maxLength={20} disabled={busy || lookingUp} placeholder="#PLAYER" onChange={event => { setCandidateTag(event.target.value); setCandidateLookup(null); }} /></label>
              <button type="button" disabled={!candidateTag.trim() || busy || lookingUp} onClick={() => void lookupCandidate()}>{lookingUp ? 'Looking up…' : 'Find player'}</button></div>
            {candidateLookup && <p><strong>{candidateLookup.account.name}</strong> · {candidateLookup.account.tag} · TH {candidateLookup.account.town_hall}{candidateLookup.account.current_clan_name ? ` · ${candidateLookup.account.current_clan_name}` : ''}</p>}
            <label>Reason for addition<textarea value={candidateReason} maxLength={500} disabled={busy} onChange={event => setCandidateReason(event.target.value)} placeholder="Why should this player enter this clan’s draw?" /></label>
            <div className="bonus-editor-actions"><button type="button" disabled={busy} onClick={() => { if (canLeaveEditor()) closeCandidate(); }}>Cancel</button>
              <button type="button" className="primary" disabled={!canManage || busy || !candidateLookup || !candidateReason.trim()} onClick={() => void (async () => {
                if (await mutate('/manual-candidates', { tag: candidateLookup!.account.tag, clan_tag: clanTag, reason: candidateReason.trim(), revision: data.revision }, 'Candidate added. Review eligibility before drawing.')) {
                  closeCandidate();
                }
              })()}>Add candidate</button></div>
          </section>}
          <p className="bonus-support">Qualifies with four attacks, or three attacks and eight stars; flags and exclusions still apply.</p>
          <details className="bonus-secondary"><summary>Eligibility rules</summary>
            <p>Three consecutive saved bonus approvals require a one-season sit-out. Earlier in-game medals not recorded here cannot be inferred.</p>
          </details>
          {clanAccounts.some(account => account.representative_status === 'unavailable') && <p className="notice error" role="alert">Discord role lookup is unavailable for one or more accounts. Eligible accounts need verified role status before drawing; refresh when Discord is available.</p>}
          <AccountList accounts={clanAccounts} onReview={(account, opener) => { if (canLeaveEditor()) { setCandidateOpen(false); setCandidateTag(''); setCandidateReason(''); setCandidateLookup(null); reviewOpener.current = opener; setReviewTag(account.tag); setPreview(null); } }} busy={busy || !canManage || archived} searchable />
          {reviewAccount && <BonusCandidateReview key={reviewAccount.tag} account={reviewAccount} busy={busy} onDirty={setReviewDirty} onCancel={() => { if (canLeaveEditor()) closeReview(); }} onRemove={reviewAccount.manual_candidate ? async () => {
            if (!window.confirm(`Remove ${reviewAccount.player_name} from this bonus candidate pool? The CWL signup and roster will stay unchanged.`)) return;
            if (await mutate('/manual-candidates', { tag: reviewAccount.tag, revision: data.revision }, 'Manual candidate removed. Review eligibility again.', 'DELETE')) { closeReview(); }
          } : undefined} onSave={async (flags, overrideReason) => {
            const saved = await mutate('/account-review', { tag: reviewAccount.tag, flags, override_reason: overrideReason, revision: data.revision }, 'Account review saved. Review eligibility again before drawing.', 'PATCH');
            if (saved) closeReview();
            return saved;
          }} />}
          <details className="bonus-secondary" onToggle={event => { if (event.currentTarget.open) void loadRoles(); }}>
            <summary>FWA Rep odds settings</summary>
            <p>Members with this Discord role receive two chances in Lazy draws. Each account can win only once. Two tickets do not guarantee twice the final winning probability when several winners are drawn.</p>
            {rolesLoading && <p role="status">Loading roles…</p>}
            {rolesError && <p role="alert">{rolesError} <button type="button" onClick={() => void loadRoles()}>Retry roles</button></p>}
            <label>Find a role<input type="search" value={roleSearch} disabled={busy} onChange={event => setRoleSearch(event.target.value)} placeholder="Role name" /></label>
            <label>Representative role<select value={roleId} disabled={busy || archived || !canManage} onChange={event => { setRoleId(event.target.value); setPreview(null); }}>
              {roleId && !roles.some(role => role.id === roleId) && <option value={roleId}>Saved role · {roleId}</option>}
              {roles.filter(role => role.id === roleId || role.name.toLowerCase().includes(roleSearch.toLowerCase())).map(role => <option key={role.id} value={role.id}>{role.name} · {role.id}</option>)}
            </select></label>
            <button type="button" disabled={!canManage || busy || archived || reviewDirty || candidateOpen || !roleDirty || !/^\d{15,22}$/.test(roleId)} onClick={() => void mutate('/lazy-settings', { representative_role_id: roleId, revision: data.revision }, 'Representative role saved. Review eligibility again before drawing.', 'PATCH')}>Save role</button>
          </details>
        </>}

        <div className="bonus-action-bar">
          <button type="button" className="primary" disabled={!canManage || busy || archived || policyDirty || roleDirty || reviewDirty || candidateOpen || !countReady || (pool === 'main' && data.policies.main === null)} onClick={() => void review()}>Review eligibility</button></div>
        {preview && <section className="bonus-preview" aria-label="Draw preview">
          <div className="bonus-section-heading"><h3>{preview.eligible.length} eligible · {Math.min(preview.available, preview.eligible.length)} winners</h3><span>{preview.available} slots remaining</span></div>
          <p>{preview.allowance_source === 'automatic' ? 'Calculated' : 'Staff-confirmed'} allowance · {preview.slots} total bonuses{pool === 'main' && preview.minimum !== null ? ` · Minimum ${preview.minimum} attacks` : ''}</p>
          {preview.available >= preview.eligible.length && <p>Every eligible account will win. Unused slots remain open.</p>}
          {!!preview.blocking_reasons.length && <div className="notice error" role="alert">{preview.blocking_reasons.map(reason => <p key={reason}>{reason}</p>)}<p>Refresh or reconcile the results before drawing.</p></div>}
          <h4>In the draw</h4><AccountList accounts={preview.eligible} mode="eligible" />
          <details className="bonus-secondary"><summary>Excluded ({preview.excluded.length})</summary><AccountList accounts={preview.excluded} mode="excluded" /></details>
          <div className="bonus-action-bar"><span>Saved draws cannot be redrawn by refreshing.</span><button type="button" className="primary" disabled={!canSaveBonusDraw({ canManage, busy, archived: !!archived, policyDirty, roleDirty, reviewDirty, reviewOpen: !!reviewTag, candidateOpen, lookingUp, blocked: !!preview.blocking_reasons.length })} onClick={() => void mutate('/draw', { pool, clan_tag: clanTag, slots: requestedSlots, fingerprint: preview.fingerprint }, 'Winners saved. Review before approving.')}>{preview.available >= preview.eligible.length ? 'Save all winners' : 'Draw and save winners'}</button></div>
        </section>}
      </section>}

      {draw && <section className="bonus-flow">
        <div className="bonus-section-heading"><div><h2>{draw.snapshot.clan_name} · Bonus winners</h2><p>Saved {new Date(draw.created_at).toLocaleString()} · {draw.approved_at ? 'Approved' : 'Awaiting staff approval'}</p></div></div>
        <div className="bonus-stats"><div><strong>{draw.snapshot.winners.length}</strong><span>Winners</span></div><div><strong>{draw.snapshot.eligible.length}</strong><span>Eligible</span></div><div><strong>{draw.snapshot.slots}</strong><span>Bonus allowance</span></div></div>
        <AccountList accounts={draw.snapshot.winners} mode="winners" />
        <details className="bonus-secondary"><summary>Draw details and all eligible accounts</summary>
          <p>{draw.snapshot.allowance_source === 'automatic' ? 'Calculated' : 'Staff-confirmed'} allowance · Saved results remain fixed if rules change later.</p>
          <AccountList accounts={draw.snapshot.eligible} mode="eligible" />
        </details>
        {!draw.approved_at && <div className="bonus-action-bar"><span>Approval records the winners. It does not send a message.</span><button type="button" className="primary" disabled={!canManage || busy || archived} onClick={() => void mutate(`/${draw.id}/approve`, {}, 'Winners approved. Review the announcement and choose a channel.')}>Approve winners</button></div>}
        {!draw.approved_at && <details className="bonus-secondary"><summary>Cancel this draw</summary><p>Cancel only if the results or setup need correction. The winners and reason remain in history.</p>
          <label>Reason<textarea maxLength={500} value={cancelReason} disabled={!canManage || busy || archived} onChange={event => setCancelReason(event.target.value)} /></label>
          <button type="button" disabled={!canManage || busy || archived || !cancelReason.trim()} onClick={() => void mutate(`/${draw.id}/cancel`, { reason: cancelReason.trim() }, 'Draw cancelled and retained in history.')}>Confirm cancellation</button></details>}
        {draw.approved_at && <BonusAnnouncement key={draw.id} draw={draw} disabled={busy || archived} onSend={(channel, retry = false) => void mutate(`/${draw.id}/send`, { channel_id: channel, retry }, 'Delivery status updated below.')} />}
      </section>}
      <details className="bonus-history"><summary>Saved bonus history ({data.history.length})</summary>
        <p className="small">Dashboard selections only; this is not proof medals were awarded in-game.</p>
        {data.draws.filter(item => item.cancelled_at).map(item => <div className="bonus-history-row" key={`cancelled-${item.id}`}><strong>{item.snapshot.clan_name} · Cancelled draw</strong><p>{item.cancel_reason}</p><small>{new Date(item.cancelled_at!).toLocaleString()}</small><AccountList accounts={item.snapshot.winners} mode="winners" /></div>)}
        {data.history.map(item => <div className="bonus-history-row" key={item.id}><strong>{item.player_name} · {item.clan_name || item.clan_tag}</strong><small>{item.tag} · {item.cycle} · {item.voided_at ? 'Voided' : 'Approved'} · {new Date(item.confirmed_at).toLocaleString()}</small></div>)}
      </details>
    </>}
  </div>;
}
