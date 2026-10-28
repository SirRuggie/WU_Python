import RosterMenu from "./rosterUi/Menu";
import TownHallIcon from "./TownHallIcon";
import { RefreshCw, Send, EyeOff } from "lucide-react";
import { Button } from "./rosterUi/primitives";
import JoiningInstructionsEditor from "./JoiningInstructionsEditor";
import { capacityWarnings, finalizeStatus } from "./publicationStatus";
import PublicationChanges from "./PublicationChanges";
import ConfirmDialog from "./ConfirmDialog";
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, type Season } from './api';
import ClanRosterImages from './ClanRosterImages';
import CwlPoolTabs, { useCwlPool } from './CwlPoolTabs';
import { useDashboardPermission } from './DashboardPermissions';
import ManageBridgeWorkspace from './ManageBridgeWorkspace';
import { type PublicationDraft, type PublicationMeta } from './publication';
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

export default function PublicationWorkspace({
  seasonId, seasons, onSeasonChange, onFix, step, onStepChange, onDirty, onBusy,
}: Props) {
  const canManage = useDashboardPermission('cwl_publish');
  const [pool, setPool] = useCwlPool();
  const [imagesOpen, setImagesOpen] = useState(false);
  const [changesReady, setChangesReady] = useState(false);
  const [confirmRevision, setConfirmRevision] = useState<number | null>(null);
  const [hideTarget, setHideTarget] = useState<{ revision: number; version: number } | null>(null);
  const [draft, setDraft] = useState<PublicationDraft | null>(null);
  const [rosterSearch, setRosterSearch] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [instructions, setInstructions] = useState('');
  const [instructionsBaseline, setInstructionsBaseline] = useState('');
  const instructionsDirty = instructions !== instructionsBaseline;
  const instructionsDirtyRef = useRef(false);
  instructionsDirtyRef.current = instructionsDirty;
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
  const pageHeading = useRef<HTMLHeadingElement>(null);
  const previousStep = useRef(step);
  useEffect(() => {
    if (previousStep.current !== step) {
      requestAnimationFrame(() => pageHeading.current?.focus({ preventScroll: true }));
      previousStep.current = step;
    }
  }, [step]);
  useEffect(() => {
    // The parent has already confirmed leaving the review step.
    if (step !== 'review') setInstructions(instructionsBaseline);
  }, [step, instructionsBaseline]);
  const mutationPending = useRef(false);
  const currentSeason = useRef(seasonId);
  currentSeason.current = seasonId;

  const locked = busy || editBusy || editOpen || editDirty || announcementBusy;
  useEffect(() => {
    onDirty?.(editDirty || announcementDirty || instructionsDirty);
    return () => onDirty?.(false);
  }, [editDirty, announcementDirty, instructionsDirty, onDirty]);
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
      const savedInstructions = result.published?.joining_instructions ?? result.last_publication?.joining_instructions ?? '';
      if (!instructionsDirtyRef.current) setInstructions(savedInstructions);
      setInstructionsBaseline(savedInstructions);
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
    setInstructions('');
    setInstructionsBaseline('');
    instructionsDirtyRef.current = false;
    setConfirmRevision(null);
    setHideTarget(null);
    setChangesReady(false);
    setAcknowledged(false);
    setError('');
    setSuccess('');
    setRosterSearch('');
    if (seasonId) void load();
    return () => { requestId.current += 1; };
  }, [seasonId, load]);

  const archived = seasons.find(season => String(season.id) === seasonId)?.status.toLowerCase() === 'archived';
  const overCapacity = draft ? capacityWarnings(draft) : { clans: 0, players: 0 };
  const checks = (['unassigned', 'missing_weight', 'over_capacity'] as const).map(filter => ({
    filter,
    accounts: draft ? readinessAccounts(draft.preview.accounts, draft.preview.clans, filter) : [],
  }));
  const hasWarnings = checks.some(check => check.accounts.length > 0);
  const canPublish = Boolean(draft && canManage && !locked && !loading && !error && !archived
    && instructions.length <= 2000 && changesReady && draft.preview.accounts.length
    && (draft.preview.unassigned_count === 0 || acknowledged));

  async function publish() {
    if (!draft || !seasonId || !canPublish || mutationPending.current) return;
    if (confirmRevision !== draft.draft_revision) {
      setConfirmRevision(null);
      setError('The draft changed. Review it again before publishing.');
      return;
    }
    setConfirmRevision(null);
    const sid = seasonId;
    mutationPending.current = true;
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
          joining_instructions: instructions,
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
      setInstructionsBaseline(instructions);
      instructionsDirtyRef.current = false;
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
      mutationPending.current = false;
      setBusy(false);
    }
  }

  async function withdraw() {
    if (!draft?.published || !seasonId || locked || loading || error || !canManage || mutationPending.current) return;
    if (!hideTarget || hideTarget.revision !== draft.draft_revision || hideTarget.version !== draft.published.version) {
      setHideTarget(null);
      setError('The draft changed. Refresh draft and review it before hiding the roster.');
      return;
    }
    setHideTarget(null);
    const sid = seasonId;
    mutationPending.current = true;
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
      mutationPending.current = false;
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
    capacity: draft?.preview.clans.find(clan => clan.tag === tag)?.effective_capacity,
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
    <div className={`publication-workspace roster-ui${step === 'review' ? ' finalize-review' : ''}`}>
      {confirmRevision !== null && draft && (
        <ConfirmDialog
          heading={`Publish version ${draft.next_version}?`}
          confirmLabel="Publish roster"
          text={`Publish the current draft for Main and Lazy? ${draft.preview.accounts.length} accounts: ${draft.preview.assigned_count} assigned and ${draft.preview.unassigned_count} awaiting placement. Members will see these assignments. No Discord message is sent.`}
          onCancel={() => setConfirmRevision(null)}
          onConfirm={() => void publish()}
          disabled={!canPublish}
        />
      )}

      {hideTarget && draft?.published && (
        <ConfirmDialog heading="Hide roster from members?" confirmLabel="Hide roster" danger
          text="Members will see no assignments until you publish again. The working roster and signups are kept. Discord messages already sent stay as they are. Publishing again creates the next version."
          onCancel={() => setHideTarget(null)} onConfirm={() => void withdraw()}
          disabled={locked || loading || !!error || !canManage} />
      )}

      <div className="page-head">
        <div>
          <p className="eyebrow">Staff · CWL</p>
          <h1 ref={pageHeading} tabIndex={-1}>{step === 'announce' ? 'Announcements' : 'Finalize roster'}</h1>
        </div>
        <RosterMenu label="Season" value={seasonId} disabled={locked || loading}
          aria-label="Season" onValueChange={onSeasonChange}
          options={[{ value: '', label: 'Select a season' }, ...seasons.map(season => ({ value: String(season.id), label: season.label }))]} />
      </div>
      {!seasonId && <div className="card empty"><p>Select a season to review its working roster.</p></div>}
      {error && (
        <div className="notice error" role="alert">
          <span>{error} Use Refresh draft to try again.</span>
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
        {!draft && seasonId && <Button icon={RefreshCw} disabled={locked || loading} onClick={() => void load()}>Refresh draft</Button>}
        {draft && (
          <>
            <section className="publication-summary" aria-label="Publication and draft status">
              <strong>{finalizeStatus(draft)}</strong>
              <Button icon={RefreshCw} disabled={locked || loading} onClick={() => void load()}>Refresh draft</Button>
            </section>
            {step === "review" && (
              <PublicationChanges seasonId={seasonId} draft={draft} onReady={setChangesReady} />
            )}
            {instructions !== (draft.published?.joining_instructions ?? '') && (
              <p className="publication-instructions-changed">Joining instructions changed</p>
            )}
            <section className="publication-readiness" aria-labelledby="publication-readiness-title">
              <h2 id="publication-readiness-title">Before you publish</h2>
              <div className="publication-check-chips">
                {checks.filter(check => check.filter !== 'over_capacity' && check.accounts.length > 0).map(check => (
                  <Button key={check.filter} disabled={locked || loading} onClick={() => onFix(check.filter)}>
                    {check.accounts.length} {check.filter === 'missing_weight' ? 'missing weights' : 'awaiting placement'} ›
                  </Button>
                ))}
                {overCapacity.clans > 0 && (
                  <Button className="publication-capacity-warning" disabled={locked || loading} onClick={() => onFix('over_capacity')}>
                    {overCapacity.clans} clans over capacity · +{overCapacity.players} ›
                  </Button>
                )}
                {!hasWarnings && <span>Checks clear</span>}
              </div>
            </section>

            <section className="publication-finalize" aria-label="Publish roster">
              <JoiningInstructionsEditor value={instructions} onChange={setInstructions}
                disabled={locked || loading || archived || !canManage} />
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
              <Button variant="primary" icon={Send} disabled={!canPublish} onClick={() => setConfirmRevision(draft.draft_revision)}>
                {busy ? 'Publishing…' : draft.published ? 'Publish updated roster' : 'Publish roster'}
              </Button>
            </section>
            <details className="publication-preview">
              <summary>Full roster preview · Main {poolCounts.main} · Lazy {poolCounts.lazy} ›</summary>
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
                        <span className={group.capacity && group.total > group.capacity ? 'publication-over' : group.total === group.capacity ? 'publication-full' : ''}>
                          {group.tag === 'unassigned' ? `${group.total} accounts` : `${group.tag} · ${group.total} / ${group.capacity ?? '—'}`}
                          {group.capacity && group.total > group.capacity ? ` · +${group.total - group.capacity} over` : ''}
                        </span>
                      </summary>
                      <div className="publication-list">
                        {group.accounts.map(account => (
                          <div key={account.tag} className="publication-row">
                            <TownHallIcon level={account.town_hall} />
                            <div>
                              <strong>{account.player_name}</strong>
                              <small>TH {account.town_hall ?? '—'} · {account.tag} · {account.pool === 'main' ? 'Main' : 'Lazy'} CWL</small>
                            </div>
                            <StaffPlayerButton
                              rosterUi
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
            </details>
            {draft.published && canManage && (
              <section className="publication-hide" aria-label="Hide roster">
                <Button variant="danger" icon={EyeOff} disabled={locked || loading || !!error}
                  onClick={() => setHideTarget({ revision: draft.draft_revision, version: draft.published!.version })}>
                  Hide roster from members
                </Button>
              </section>
            )}


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
