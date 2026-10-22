import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, type Season } from './api';
import ClanRosterImages from './ClanRosterImages';
import CwlPoolTabs, { useCwlPool } from './CwlPoolTabs';
import { useDashboardPermission } from './DashboardPermissions';
import ManageBridgeWorkspace from './ManageBridgeWorkspace';
import { draftPublicationStatus, type PublicationDraft, type PublicationMeta } from './publication';
import { readinessAccounts, type ReadinessFilter } from './readiness';
import StaffPlayerButton from './StaffPlayerButton';
import './publicationFlow.css';

type Step = 'review' | 'announce';
type Props = {
  seasonId: string;
  seasons: Season[];
  onSeasonChange: (id: string) => void;
  onFix: (filter: ReadinessFilter) => void;
  step: Step;
  onStepChange: (step: Step) => void;
  onDirty?: (dirty: boolean) => void;
  onBusy?: (busy: boolean) => void;
};

const errorText = (error: unknown) => error instanceof Error
  ? error.message
  : 'Publication request failed. Try again.';
const dateText = (value: string) => new Date(value).toLocaleString();
const checkLabels: Record<Exclude<ReadinessFilter, 'all'>, string> = {
  unassigned: 'Unassigned accounts',
  missing_weight: 'Missing weights',
  over_capacity: 'Accounts in clans over capacity',
};

export default function PublicationWorkspace({
  seasonId, seasons, onSeasonChange, onFix, step, onStepChange, onDirty, onBusy,
}: Props) {
  const canManage = useDashboardPermission('cwl_publish');
  const [pool, setPool] = useCwlPool();
  const [imagesOpen, setImagesOpen] = useState(false);
  const [draft, setDraft] = useState<PublicationDraft | null>(null);
  const [rosterSearch, setRosterSearch] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [editDirty, setEditDirty] = useState(false);
  const [editBusy, setEditBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [announcementDirty, setAnnouncementDirty] = useState(false);
  const [announcementBusy, setAnnouncementBusy] = useState(false);
  const requestId = useRef(0);
  const currentSeason = useRef(seasonId);
  currentSeason.current = seasonId;

  const locked = busy || editBusy || editOpen || editDirty || announcementBusy;
  useEffect(() => {
    onDirty?.(editDirty || announcementDirty);
    return () => onDirty?.(false);
  }, [editDirty, announcementDirty, onDirty]);
  useEffect(() => {
    onBusy?.(busy || editBusy || editOpen || announcementBusy);
    return () => onBusy?.(false);
  }, [busy, editBusy, editOpen, announcementBusy, onBusy]);

  const load = useCallback(async () => {
    if (!seasonId) return;
    const sid = seasonId;
    const id = ++requestId.current;
    setLoading(true);
    setError('');
    try {
      const result = await api<PublicationDraft>(`/seasons/${encodeURIComponent(sid)}/publication`);
      if (id !== requestId.current || currentSeason.current !== sid) return;
      setDraft(result);
      setAcknowledged(false);
    } catch (cause) {
      if (id === requestId.current && currentSeason.current === sid) {
        // Never leave a protected roster from an earlier successful read on screen.
        setDraft(null);
        setError(errorText(cause));
      }
    } finally {
      if (id === requestId.current && currentSeason.current === sid) setLoading(false);
    }
  }, [seasonId]);

  useEffect(() => {
    requestId.current += 1;
    setDraft(null);
    setAcknowledged(false);
    setError('');
    setSuccess('');
    setRosterSearch('');
    if (seasonId) void load();
  }, [seasonId, load]);

  const archived = seasons.find(season => String(season.id) === seasonId)?.status.toLowerCase() === 'archived';
  const status = draft ? draftPublicationStatus(draft) : null;
  const checks = (['unassigned', 'missing_weight', 'over_capacity'] as const).map(filter => ({
    filter,
    accounts: draft ? readinessAccounts(draft.preview.accounts, draft.preview.clans, filter) : [],
  }));
  const hasWarnings = checks.some(check => check.accounts.length > 0);
  const canPublish = Boolean(draft && canManage && !locked && !loading && !error && !archived
    && draft.preview.accounts.length
    && (draft.preview.unassigned_count === 0 || acknowledged));

  async function publish() {
    if (!draft || !seasonId || !canPublish) return;
    const total = draft.preview.accounts.length;
    const assigned = draft.preview.assigned_count;
    const unassigned = draft.preview.unassigned_count;
    if (!window.confirm(
      `Publish this working roster for both Main and Lazy CWL? ${total} accounts: ${assigned} assigned and ${unassigned} awaiting placement. Members will be able to see these assignments. This does not send a Discord announcement.`,
    )) return;
    const sid = seasonId;
    setBusy(true);
    setError('');
    setSuccess('');
    try {
      const result = await api<{ published: PublicationMeta }>(
        `/seasons/${encodeURIComponent(sid)}/publication`,
        'POST',
        {
          revision: draft.draft_revision,
          acknowledge_unassigned: acknowledged,
          joining_instructions: draft.published?.joining_instructions || '',
        },
      );
      if (currentSeason.current !== sid) return;
      setDraft(current => current ? {
        ...current,
        draft_revision: result.published.revision + 1,
        draft_changed: false,
        published: result.published,
      } : current);
      setAcknowledged(false);
      onStepChange('announce');
      setSuccess(`Version ${result.published.version} published. Members can now view these assignments.`);
      await load();
    } catch (cause) {
      if (currentSeason.current === sid) {
        if (cause instanceof ApiError && cause.status === 403) setDraft(null);
        setError(cause instanceof ApiError && cause.status === 409
          ? `${cause.message} Refresh the draft and review it before publishing.`
          : errorText(cause));
      }
    } finally {
      setBusy(false);
    }
  }

  async function withdraw() {
    if (!draft?.published || !seasonId || locked || loading || error || !canManage) return;
    if (!window.confirm(
      'Hide published assignments from members? Signups and the working roster will be kept. Existing Discord messages will not be removed.',
    )) return;
    const sid = seasonId;
    setBusy(true);
    setError('');
    setSuccess('');
    try {
      await api(`/seasons/${encodeURIComponent(sid)}/publication/withdraw`, 'POST', {
        revision: draft.draft_revision,
        version: draft.published.version,
      });
      if (currentSeason.current !== sid) return;
      setSuccess('Publication withdrawn. Members will see assignments only after you publish again.');
      await load();
    } catch (cause) {
      if (currentSeason.current === sid) {
        if (cause instanceof ApiError && cause.status === 403) setDraft(null);
        setError(errorText(cause));
      }
    } finally {
      setBusy(false);
    }
  }

  const clanNames = new Map(draft?.preview.clans.map(clan => [clan.tag, clan.name]));
  const rosterGroups = new Map<string, {
    name: string;
    accounts: NonNullable<typeof draft>['preview']['accounts'];
  }>();
  const poolCounts = { main: 0, lazy: 0 };
  for (const account of draft?.preview.accounts || []) {
    const hostingPool = draft?.preview.clans.find(clan => clan.tag === account.assigned_clan_tag)?.pool || account.pool;
    poolCounts[hostingPool] += 1;
    if (hostingPool !== pool) continue;
    const key = account.assigned_clan_tag || 'unassigned';
    const name = account.assigned_clan_tag
      ? clanNames.get(account.assigned_clan_tag) || account.assigned_clan_tag
      : 'Awaiting placement';
    const group = rosterGroups.get(key) || { name, accounts: [] };
    group.accounts.push(account);
    rosterGroups.set(key, group);
  }
  const query = rosterSearch.trim().toLowerCase();
  const visibleGroups = [...rosterGroups].map(([tag, group]) => ({
    tag,
    name: group.name,
    total: group.accounts.length,
    accounts: query ? group.accounts.filter(account =>
      [account.player_name, account.tag, account.pool, group.name, tag]
        .some(value => value.toLowerCase().includes(query))) : group.accounts,
  })).filter(group => group.accounts.length).sort((left, right) => {
    if (left.tag === 'unassigned') return 1;
    if (right.tag === 'unassigned') return -1;
    return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' }) || left.tag.localeCompare(right.tag);
  });
  const visibleCount = visibleGroups.reduce((total, group) => total + group.accounts.length, 0);

  return (
    <div className="publication-workspace">
      <div className="page-head">
        <div>
          <p className="eyebrow">Staff · CWL</p>
          <h1>{step === 'announce' ? 'Announcements' : 'Finalize roster'}</h1>
          <p>{step === 'announce'
            ? 'Review the message before choosing where to send it.'
            : 'Review Main and Lazy assignments before members can see them.'}</p>
        </div>
        <label className="season-choice">
          Season
          <select value={seasonId} disabled={locked || loading} onChange={event => onSeasonChange(event.target.value)}>
            <option value="">Select a season</option>
            {seasons.map(season => <option key={season.id} value={String(season.id)}>{season.label}</option>)}
          </select>
        </label>
      </div>
      {!seasonId && <div className="card empty"><p>Select a season to review its working roster.</p></div>}
      {error && (
        <div className="notice error" role="alert">
          <span>{error}</span>
          <button disabled={locked || loading} onClick={() => void load()}>Refresh draft</button>
        </div>
      )}
      {success && (
        <div className="notice success" role="status">
          {success}
          {draft?.published && step !== 'announce' && <button type="button" onClick={() => onStepChange('announce')}>Continue to announcements</button>}
        </div>
      )}
      {loading && !draft && <p role="status">Loading publication preview…</p>}

      <div hidden={step !== 'review'}>
        {draft && (
          <>
            <section className="publication-summary" aria-label="Publication and draft status">
              <div>
                <strong>{status === 'unpublished'
                  ? 'Not published'
                  : status === 'changed'
                    ? 'Published version has draft changes'
                    : 'Published roster is current'}</strong>
                <span>{status === 'unpublished'
                  ? 'Members cannot see placements yet.'
                  : status === 'changed'
                    ? 'Members still see the previous published assignments.'
                    : 'Members can see this roster.'}</span>
              </div>
              <div className="publication-counts">
                <span><strong>{draft.preview.accounts.length}</strong> accounts</span>
                <span><strong>{draft.preview.assigned_count}</strong> assigned</span>
                <span><strong>{draft.preview.unassigned_count}</strong> awaiting placement</span>
              </div>
              {draft.published && (
                <details className="publication-version">
                  <summary>Published version {draft.published.version} · {dateText(draft.published.published_at)}</summary>
                  <p>{draft.published.assigned_count} assigned · {draft.published.unassigned_count} awaiting placement</p>
                  {canManage && (
                    <button disabled={locked || loading || !!error} onClick={() => void withdraw()}>
                      Hide published assignments
                    </button>
                  )}
                </details>
              )}
            </section>

            <section className="publication-readiness" aria-labelledby="publication-readiness-title">
              <div className="publication-section-heading">
                <h2 id="publication-readiness-title">Readiness checks</h2>
                <span>{hasWarnings ? 'Review the flagged accounts' : draft.preview.accounts.length ? 'Checks clear' : 'Waiting for signups'}</span>
              </div>
              <p>Missing weights do not block publication. Unassigned accounts need your acknowledgement.</p>
              <div className="publication-check-list">
                {checks.map(check => (
                  <div className="publication-check" key={check.filter}>
                    <span><strong>{checkLabels[check.filter]}</strong><small>{check.accounts.length} account{check.accounts.length === 1 ? '' : 's'}</small></span>
                    {check.accounts.length > 0
                      ? <button disabled={locked || loading} onClick={() => onFix(check.filter)}>Review in roster →</button>
                      : <span>✓ Clear</span>}
                  </div>
                ))}
              </div>
            </section>

            <section className="publication-preview" aria-labelledby="publication-preview-title">
              <div className="publication-section-heading">
                <div>
                  <h2 id="publication-preview-title">Preview assignments by clan</h2>
                  <p>Main {poolCounts.main} · Lazy {poolCounts.lazy}. Both groups are included when you publish.</p>
                </div>
                <button disabled={locked || loading} onClick={() => void load()}>Refresh draft</button>
              </div>
              <div className="publication-preview-filters">
                <CwlPoolTabs value={pool} onChange={setPool} disabled={locked || loading} />
                <label>
                  Find an account or clan
                  <input
                    type="search"
                    value={rosterSearch}
                    disabled={locked || loading}
                    onChange={event => setRosterSearch(event.target.value)}
                    placeholder="Name, tag, pool, or clan"
                  />
                </label>
              </div>
              {query && <p className="publication-result-count">{visibleCount} matching account{visibleCount === 1 ? '' : 's'}</p>}
              {visibleGroups.length ? (
                <div className="publication-groups">
                  {visibleGroups.map(group => (
                    <details key={`${group.tag}:${query}`} className="publication-group" open={!!query}>
                      <summary>
                        <strong>{group.name}</strong>
                        <span>{group.tag === 'unassigned' ? '' : `${group.tag} · `}
                          {query ? `${group.accounts.length} of ${group.total}` : group.total}
                          {' '}account{group.total === 1 ? '' : 's'}</span>
                      </summary>
                      <div className="publication-list">
                        {group.accounts.map(account => (
                          <div key={account.tag} className="publication-row">
                            <div>
                              <strong>{account.player_name}</strong>
                              <small>{account.tag} · TH {account.town_hall ?? '—'} · {account.pool === 'main' ? 'Main' : 'Lazy'} CWL</small>
                            </div>
                            <span className={account.assigned_clan_tag ? '' : 'publication-unassigned'}>
                              {account.assigned_clan_tag ? group.name : 'Awaiting placement'}
                            </span>
                            <StaffPlayerButton
                              seasonId={seasonId}
                              tag={account.tag}
                              disabled={locked || archived}
                              onChanged={load}
                              onDirty={setEditDirty}
                              onBusy={setEditBusy}
                              onOpenChange={setEditOpen}
                            >
                              Details<span className="publication-visually-hidden"> for {account.player_name}</span>
                            </StaffPlayerButton>
                          </div>
                        ))}
                      </div>
                    </details>
                  ))}
                </div>
              ) : draft.preview.accounts.length ? (
                <p>No {pool === 'main' ? 'Main' : 'Lazy'} accounts match this view.</p>
              ) : (
                <p>No signup accounts are in the working roster.</p>
              )}
            </section>

            <section className="publication-finalize" aria-labelledby="publication-finalize-title">
              <div className="publication-section-heading">
                <div>
                  <h2 id="publication-finalize-title">Publish this roster</h2>
                  <p>Publishes Main and Lazy placements together for members. Discord announcements are a separate step.</p>
                </div>
              </div>
              {draft.preview.unassigned_count > 0 && (
                <label className="publication-ack">
                  <input
                    type="checkbox"
                    checked={acknowledged}
                    disabled={locked}
                    onChange={event => setAcknowledged(event.target.checked)}
                  />
                  <span>I understand {draft.preview.unassigned_count} account{draft.preview.unassigned_count === 1 ? ' is' : 's are'} still awaiting placement and will appear that way to members.</span>
                </label>
              )}
              {archived && <p className="inline-reason">This season is archived. Its roster cannot be published or republished.</p>}
              {!draft.preview.accounts.length && <p className="inline-reason">No signed-up accounts are in this roster yet.</p>}
              <button className="primary" disabled={!canPublish} onClick={() => void publish()}>
                {busy ? 'Publishing…' : draft.published ? 'Publish updated roster' : 'Publish roster'}
              </button>
            </section>
          </>
        )}
      </div>
      {seasonId && step === 'announce' && (
        <div>
          <ManageBridgeWorkspace onDirty={setAnnouncementDirty} onBusy={setAnnouncementBusy} seasonId={seasonId} publicationVersion={draft?.published?.version ?? null} />
          <details className="card" onToggle={event => setImagesOpen(event.currentTarget.open)}>
            <summary>Clan roster images &amp; testing</summary>
            {imagesOpen && <ClanRosterImages key={seasonId} seasonId={seasonId} version={draft?.published?.version ?? null} />}
          </details>
        </div>
      )}
    </div>
  );
}
