import type { MemberOption } from "./MemberPicker";
import RosterDiscordIdentity from "./RosterDiscordIdentity";
import { rosterAccountPages, rosterMemberKey } from "./rosterGrouping";
import DashboardIcon from "./DashboardIcon";
import SignupActivity from "./SignupActivity";
import useWorkspacePreference from "./useWorkspacePreference";
import useUnsavedWork from "./useUnsavedWork";
import ClanDestinationOptions from "./ClanDestinationOptions";
import CwlPoolTabs, { useCwlPool } from "./CwlPoolTabs";
import RosterPlayerDialog from "./RosterPlayerDialog";
import RosterSignupActions from "./RosterSignupActions";
import StaffSignupControls from "./StaffSignupControls";
import { useDashboardPermission } from "./DashboardPermissions";
import TownHallIcon from "./TownHallIcon";
import "./RosterWorkspace.css";
import {
  FilterPicker,
  leagueValue,
  matchesLeague,
  matchesTownHall,
} from "./ClanFilters";
import { sortClans } from "./clanSort";
import WeightQueue from "./WeightQueue";
import { readinessAccounts, type ReadinessFilter } from "./readiness";
import CompareClans from "./CompareClans";
import {
  Fragment,
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, ApiError, type Pool, type Season } from "./api";
import {
  assignmentOptions,
  filterRosterAccounts,
  sortRosterAccounts,
  parseWeightK,
  weightInputText,
  weightText,
  type AutoPreview,
  type RosterClan,
  type RosterSnapshot,
  type RosterSort,
} from "./roster";

type Props = {
  seasonId: string;
  seasons: Season[];
  onDirty?: (dirty: boolean) => void;
  onSeasonChange: (id: string) => void;
  initialReadiness?: ReadinessFilter;
  onReviewPublication?: () => void;
  onSeasonRefresh?: () => Promise<void>;
  onBusy?: (busy: boolean) => void;
};
type Feedback = { kind: "success" | "error"; text: string };
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "The roster request failed. Try again.";
const encoded = (value: string) => encodeURIComponent(value);

export default function RosterWorkspace({
  seasonId,
  seasons,
  onSeasonChange,
  initialReadiness = "all",
  onReviewPublication,
  onSeasonRefresh,
  onBusy,
  onDirty,
}: Props) {
  const canRoster = useDashboardPermission("cwl_roster");
  const canSignups = useDashboardPermission("cwl_signups");
  const season = seasons.find((item) => String(item.id) === seasonId);
  const archived = season?.status === "archived";
  const [editingTag, setEditingTag] = useState<string | null>(null);
  const [roster, setRoster] = useState<RosterSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [preview, setPreview] = useState<AutoPreview | null>(null);
  const [mode, setMode] = useWorkspacePreference<
    "assign" | "compare" | "rules" | "weights"
  >(`wu-roster-${seasonId}-mode`, "assign");
  const [page, setPage] = useWorkspacePreference(
    `wu-roster-${seasonId}-page`,
    0,
  );
  const [manualTag, setManualTag] = useState<string | null>(null);
  const [manualClan, setManualClan] = useState("");
  const [ruleTag, setRuleTag] = useWorkspacePreference(
    `wu-roster-${seasonId}-clan`,
    "",
  );
  const [leagues, setLeagues] = useWorkspacePreference<string[]>(
    `wu-roster-${seasonId}-leagues`,
    [],
  );
  const [townHalls, setTownHalls] = useWorkspacePreference<string[]>(
    `wu-roster-${seasonId}-townhalls`,
    [],
  );
  const [search, setSearch] = useWorkspacePreference(
    `wu-roster-${seasonId}-search`,
    "",
  );
  const [readinessFilter, setReadinessFilter] =
    useState<ReadinessFilter>(initialReadiness);
  const [poolFilter, setPoolFilter] = useCwlPool();
  const [listPool, setListPool] = useWorkspacePreference<Pool | "all">(
    `wu-roster-${seasonId}-list-pool`,
    "all",
  );
  const viewPool = mode === "assign" ? listPool : poolFilter;
  const [assignmentFilter, setAssignmentFilter] = useWorkspacePreference<
    "all" | "assigned" | "unassigned"
  >(`wu-roster-${seasonId}-assignment`, "all");
  const [sort, setSort] = useWorkspacePreference<RosterSort>(
    `wu-roster-${seasonId}-sort`,
    "name",
  );
  const [groupByDiscord, setGroupByDiscord] = useState(false);
  const [groupMembers, setGroupMembers] = useState<Record<string, MemberOption>>({});
  const [groupNamesLoading, setGroupNamesLoading] = useState(false);
  const [groupNamesError, setGroupNamesError] = useState(false);
  const [groupNamesRetry, setGroupNamesRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setGroupMembers({});
    setGroupNamesError(false);
    setGroupNamesLoading(groupByDiscord);
    if (!groupByDiscord) return;
    api<{ options: MemberOption[] }>(`/staff-signup-members?season_id=${encoded(seasonId)}`)
      .then(data => {
        if (active) setGroupMembers(Object.fromEntries(data.options.map(member => [member.id, member])));
      })
      .catch(() => { if (active) setGroupNamesError(true); })
      .finally(() => { if (active) setGroupNamesLoading(false); });
    return () => { active = false; };
  }, [groupByDiscord, seasonId, groupNamesRetry]);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [bulkDestination, setBulkDestination] = useState("");
  const [rulesDirty, setRulesDirty] = useState(false);
  const [weightsDirty, setWeightsDirty] = useState(false);
  const [playerDirty, setPlayerDirty] = useState(false);
  const [signupDirty, setSignupDirty] = useState(false);
  const [signupBusy, setSignupBusy] = useState(false);
  const [signupReviewOpen, setSignupReviewOpen] = useState(false);
  const [signupOpen, setSignupOpen] = useState(false);
  const working = busy || signupBusy;
  const uiLocked = working || signupReviewOpen || signupOpen;
  const dirty =
    rulesDirty ||
    weightsDirty ||
    playerDirty ||
    signupDirty ||
    signupReviewOpen ||
    !!manualTag ||
    selectedTags.length > 0;
  useUnsavedWork(dirty || working, onDirty);
  useEffect(() => {
    onBusy?.(working);
    return () => onBusy?.(false);
  }, [working, onBusy]);
  useEffect(() => {
    if (!canRoster && mode !== "assign") setMode("assign");
  }, [canRoster, mode, setMode]);
  const mayLeaveEditor = () =>
    !working &&
    (!dirty || window.confirm("Discard unsaved roster edits and selections?"));
  const listHeading = useRef<HTMLDivElement>(null);
  const focusListHeading = () => requestAnimationFrame(() => requestAnimationFrame(() => listHeading.current?.focus({ preventScroll: true })));
  const requestId = useRef(0);
  const activeSeason = useRef(seasonId);
  activeSeason.current = seasonId;

  const refresh = useCallback(async () => {
    if (!seasonId) return null;
    const id = ++requestId.current;
    try {
      const snapshot = await api<RosterSnapshot>(
        `/seasons/${encoded(seasonId)}/roster`,
      );
      if (id !== requestId.current || activeSeason.current !== seasonId) return null;
      setRoster(snapshot);
      return snapshot;
    } catch (error) {
      if (id === requestId.current && activeSeason.current === seasonId &&
          error instanceof ApiError && [401, 403].includes(error.status)) {
        setRoster(null);
        setSelectedTags([]);
        setEditingTag(null);
        setManualTag(null);
        setPreview(null);
      }
      throw error;
    }
  }, [seasonId]);
  useEffect(() => {
    setEditingTag(null);
    setManualTag(null);
    setRoster(null);
    setPreview(null);
    setFeedback(null);
    setSelectedTags([]);
    setBulkDestination("");
    if (!seasonId) return;
    let alive = true;
    setLoading(true);
    void refresh()
      .catch((error) => {
        if (alive) setFeedback({ kind: "error", text: errorText(error) });
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
      requestId.current++;
    };
  }, [seasonId, refresh]);

  const afterWrite = async (success: string) => {
    setPreview(null);
    try {
      await refresh();
      setFeedback({ kind: "success", text: success });
    } catch (error) {
      setFeedback({
        kind: "error",
        text: `${success} The latest roster could not be loaded: ${errorText(error)}`,
      });
    }
  };
  const fail = async (error: unknown) => {
    if (error instanceof ApiError && [401, 403].includes(error.status)) {
      setRoster(null);
      setSelectedTags([]);
      setEditingTag(null);
      setManualTag(null);
      setPreview(null);
      setFeedback({ kind: "error", text: error.message });
      return;
    }
    if (error instanceof ApiError && error.status === 409) {
      const hadAccountEditor = !!editingTag || !!manualTag;
      const hadManualPlacement = !!manualTag;
      setEditingTag(null);
      setManualTag(null);
      try {
        await refresh();
      } catch {
        /* Original conflict remains the useful error. */
      }
      setPreview(null);
      setFeedback({
        kind: "error",
        text: hadAccountEditor
          ? `${error.message} The account editor closed. Reopen it to review the latest saved values.`
          : `${error.message} The roster was refreshed; review it and try again.`,
      });
      if (hadManualPlacement) focusListHeading();
    } else setFeedback({ kind: "error", text: errorText(error) });
  };
  const edit = async (
    tag: string,
    body: Record<string, unknown>,
    success: string,
  ): Promise<boolean> => {
    if (!canRoster || !roster || !seasonId || working || archived) return false;
    const sid = seasonId;
    setBusy(true);
    setFeedback(null);
    try {
      await api(`/seasons/${encoded(sid)}/roster/${encoded(tag)}`, "PATCH", {
        revision: roster.revision,
        ...body,
      });
      if (activeSeason.current === sid) await afterWrite(success);
      return true;
    } catch (error) {
      if (activeSeason.current === sid) await fail(error);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const removeSignup = async (tag: string): Promise<boolean> => {
    if (!canSignups || !roster || !seasonId || working || archived) return false;
    const sid = seasonId;
    setBusy(true);
    setFeedback(null);
    try {
      await api(
        `/seasons/${encoded(sid)}/staff-signups/${encoded(tag)}`,
        "DELETE",
        { revision: roster.revision },
      );
      if (activeSeason.current === sid) {
        setSelectedTags((tags) => tags.filter((value) => value !== tag));
        await afterWrite(
          "Signup removed. Publish again to update the published roster.",
        );
      }
      return true;
    } catch (error) {
      if (activeSeason.current === sid) await fail(error);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const saveRules = async (
    clan: RosterClan,
    rules: {
      pool: Pool;
      capacity: number;
      min_weight: number | null;
      max_weight: number | null;
      lower_league: boolean | null;
    },
  ) => {
    if (!canRoster || !roster || !seasonId || working || archived) return false;
    const sid = seasonId;
    setBusy(true);
    setFeedback(null);
    try {
      await api(
        `/seasons/${encoded(sid)}/lineup/${encoded(clan.tag)}/rules`,
        "PATCH",
        { revision: roster.revision, ...rules },
      );
      if (activeSeason.current === sid)
        await afterWrite(`${clan.name} placement rules saved.`);
      return true;
    } catch (error) {
      if (activeSeason.current === sid) await fail(error);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const previewPlacement = async () => {
    if (!canRoster || !roster || !seasonId || working || archived) return;
    const sid = seasonId;
    setBusy(true);
    setFeedback(null);
    setPreview(null);
    try {
      const result = await api<AutoPreview>(
        `/seasons/${encoded(sid)}/roster/auto-preview`,
        "POST",
        { revision: roster.revision, pool: poolFilter },
      );
      if (activeSeason.current === sid) setPreview(result);
    } catch (error) {
      if (activeSeason.current === sid) await fail(error);
    } finally {
      setBusy(false);
    }
  };
  const applyPlacement = async () => {
    if (
      !preview ||
      !roster ||
      !seasonId ||
      !canRoster ||
      uiLocked ||
      archived ||
      preview.revision !== roster.revision
    )
      return;
    const sid = seasonId;
    setBusy(true);
    setFeedback(null);
    try {
      const result = await api<{ revision: number; applied: number }>(
        `/seasons/${encoded(sid)}/roster/auto-apply`,
        "POST",
        {
          revision: preview.revision,
          pool: poolFilter,
          placements: preview.placements,
        },
      );
      if (activeSeason.current === sid)
        await afterWrite(
          `${result.applied} account${result.applied === 1 ? "" : "s"} placed from the reviewed preview.`,
        );
    } catch (error) {
      if (activeSeason.current === sid) await fail(error);
    } finally {
      setBusy(false);
    }
  };
  const refreshWeights = async () => {
    if (!canRoster || !roster || !seasonId || working || archived) return;
    const sid = seasonId;
    setBusy(true);
    setFeedback(null);
    try {
      const result = await api<{
        revision: number;
        refreshed: number;
        missing: number;
      }>(`/seasons/${encoded(sid)}/roster/refresh-weights`, "POST", {
        revision: roster.revision,
      });
      if (activeSeason.current === sid)
        await afterWrite(
          `Weight refresh finished: ${result.refreshed} refreshed, ${result.missing} missing.`,
        );
    } catch (error) {
      if (activeSeason.current === sid) {
        try {
          await refresh();
        } catch {
          /* Preserve source error. */
        }
        await fail(error);
      }
    } finally {
      setBusy(false);
    }
  };
  const filtered = roster
    ? sortRosterAccounts(
        filterRosterAccounts(
          readinessAccounts(roster.accounts, roster.clans, readinessFilter),
          search,
          viewPool,
          assignmentFilter,
        ).filter(
          (account) =>
            matchesTownHall(account.town_hall, townHalls) &&
            (!leagues.length ||
              (!!account.assigned_clan_tag &&
                matchesLeague(
                  roster.clans.find(
                    (clan) => clan.tag === account.assigned_clan_tag,
                  )?.cwl_league,
                  leagues,
                ))),
        ),
        sort,
      )
    : [];
  const accountPages = rosterAccountPages(filtered, groupByDiscord);
  const lastPage = Math.max(0, accountPages.length - 1);
  const currentPage = Math.min(page, lastPage);
  const pageAccounts = accountPages[currentPage] || [];
  const filterKey = JSON.stringify([
    search,
    viewPool,
    assignmentFilter,
    readinessFilter,
    leagues,
    townHalls,
  ]);
  const previousFilter = useRef(filterKey);
  useEffect(() => {
    if (previousFilter.current !== filterKey) {
      setPage(0);
      setSelectedTags([]);
      setManualTag(null);
      previousFilter.current = filterKey;
    }
  }, [filterKey]);
  const visibleTags = pageAccounts.map((account) => account.tag);
  const hiddenSelection = selectedTags.filter((tag) => !visibleTags.includes(tag)).length;
  const staleSelection = selectedTags.filter((tag) => !filtered.some((account) => account.tag === tag)).length;
  const selectingPageWouldExceedLimit = new Set([...selectedTags, ...visibleTags]).size > 50;
  const allVisibleSelected =
    visibleTags.length > 0 &&
    visibleTags.every((tag) => selectedTags.includes(tag));
  const toggleSelected = (tag: string) =>
    setSelectedTags((current) =>
      current.includes(tag)
        ? current.filter((item) => item !== tag)
        : [...current, tag],
    );
  const bulkAssign = async () => {
    if (!canRoster || viewPool === "all" || !roster || !seasonId || working || archived || !selectedTags.length) return;
    if (staleSelection) {
      setFeedback({
        kind: "error",
        text: "The roster changed since selection. Clear selection and choose accounts again.",
      });
      return;
    }
    if (selectedTags.length > 50) {
      setFeedback({
        kind: "error",
        text: "Select up to 50 accounts per bulk assignment.",
      });
      return;
    }
    if (
      bulkDestination &&
      bulkDestination !== "__unassign__" &&
      !assignmentOptions(roster.clans, poolFilter).some(
        (clan) => clan.tag === bulkDestination,
      )
    ) {
      setFeedback({ kind: "error", text: "Choose an active hosting clan." });
      return;
    }
    if (!bulkDestination) {
      setFeedback({
        kind: "error",
        text: "Choose a hosting clan or Unassign selected.",
      });
      return;
    }
    const actionSummary = bulkDestination === "__unassign__"
      ? `Unassign ${selectedTags.length} selected account${selectedTags.length === 1 ? "" : "s"} from the working roster?`
      : `Assign ${selectedTags.length} selected account${selectedTags.length === 1 ? "" : "s"} to ${clanName(bulkDestination)}?`;
    if (!window.confirm(`${actionSummary} Published assignments remain visible until you publish again.`)) return;
    const sid = seasonId;
    setBusy(true);
    setFeedback(null);
    try {
      const result = await api<{ revision: number; updated: number }>(
        `/seasons/${encoded(sid)}/roster/assignments`,
        "PATCH",
        {
          revision: roster.revision,
          tags: selectedTags,
          assigned_clan_tag:
            bulkDestination === "__unassign__" ? null : bulkDestination,
        },
      );
      if (activeSeason.current === sid) {
        setSelectedTags([]);
        await afterWrite(
          `${result.updated} account${result.updated === 1 ? "" : "s"} ${bulkDestination === "__unassign__" ? "unassigned" : "assigned to " + clanName(bulkDestination)}.`,
        );
      }
    } catch (error) {
      if (activeSeason.current === sid) await fail(error);
    } finally {
      setBusy(false);
    }
  };
  const bulkChangeSignups = async (
    action: Pool | "remove",
    tags: string[],
  ): Promise<boolean> => {
    if (!canSignups || !roster || !seasonId || working || archived || !tags.length || tags.length > 50) return false;
    const available = new Set(roster.accounts.map((account) => account.tag));
    if (tags.some((tag) => !available.has(tag))) {
      setFeedback({ kind: "error", text: "The selection changed. Clear it and choose the accounts again." });
      return false;
    }
    const sid = seasonId;
    setBusy(true);
    setFeedback(null);
    try {
      const result = await api<{ count: number }>(
        `/seasons/${encoded(sid)}/staff-signup-changes`,
        "POST",
        { revision: roster.revision, tags, action },
      );
      if (activeSeason.current === sid) {
        const fromBulk = selectedTags.length > 0;
        setSelectedTags([]);
        await afterWrite(`${result.count} signup${result.count === 1 ? "" : "s"} ${action === "remove" ? "removed" : `changed to ${action === "main" ? "Main" : "Lazy"} CWL`}. Publish again to update the published roster.`);
        if (fromBulk) focusListHeading();
      }
      return true;
    } catch (error) {
      if (activeSeason.current === sid) {
        if (error instanceof ApiError && error.status === 409) {
          const fromBulk = selectedTags.length > 0;
          setSelectedTags([]);
          setEditingTag(null);
          await fail(error);
          if (fromBulk) focusListHeading();
        } else {
          await fail(error);
        }
      }
      return false;
    } finally {
      setBusy(false);
    }
  };
  const undoPlacement = async () => {
    if (!canRoster || !roster?.undo || !seasonId || uiLocked || archived) return;
    const sid = seasonId;
    setBusy(true);
    setFeedback(null);
    try {
      await api(`/seasons/${encoded(sid)}/roster/undo`, "POST", {
        revision: roster.revision,
        undo_id: roster.undo.id,
      });
      if (activeSeason.current === sid)
        await afterWrite("Last placement change undone.");
    } catch (error) {
      if (activeSeason.current === sid) {
        if (!(error instanceof ApiError && error.status === 409)) {
          try {
            await refresh();
          } catch {
            /* Keep original error. */
          }
        }
        await fail(error);
      }
    } finally {
      setBusy(false);
    }
  };
  const poolAccounts =
    roster?.accounts.filter((account) => viewPool === "all" || account.pool === viewPool) || [];
  const assigned =
    poolAccounts.filter((account) => !!account.assigned_clan_tag).length || 0;
  const missingWeight =
    poolAccounts.filter((account) => account.effective_weight === null)
      .length || 0;
  const activeClans =
    roster?.clans.filter(
      (clan) => !clan.archived && (clan.pool === poolFilter || !clan.pool),
    ) || [];
  const ruleClan =
    activeClans.find((clan) => clan.tag === ruleTag) || activeClans[0];
  const selectedAccounts = selectedTags
    .map((tag) => roster?.accounts.find((account) => account.tag === tag))
    .filter((account): account is NonNullable<typeof account> => !!account);
  const clanName = (tag: string | null) =>
    roster?.clans.find((clan) => clan.tag === tag)?.name || tag || "Unassigned";

  return (
    <div className={`roster-workspace${mode === "assign" ? " roster-workspace-assign" : ""}`}>
      <div className="page-head">
        <div>
          <p className="eyebrow">Staff roster</p>
          <h1>CWL roster &amp; signups</h1>
          <p>{mode === "assign"
            ? "Manage signups and working placements. Placements stay private until published."
            : "Select accounts, choose a hosting clan, and assign. Changes save immediately."}</p>
        </div>
        <label className="season-choice">
          Season
          <select
            value={seasonId}
            disabled={uiLocked}
            onChange={(event) => {
              if (mayLeaveEditor()) onSeasonChange(event.target.value);
            }}
          >
            <option value="">Select a season</option>
            {seasons.map((season) => (
              <option key={season.id} value={String(season.id)}>
                {season.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {seasonId && canSignups && <SignupActivity key={seasonId} seasonId={seasonId} />}
      {!seasonId && (
        <div className="card empty">
          <p>Select a season to build its CWL roster.</p>
        </div>
      )}
      {feedback && (
        <div
          className={`notice ${feedback.kind}`}
          role={feedback.kind === "error" ? "alert" : "status"}
        >
          {feedback.text}
          {feedback.kind === "error" && !roster && (
            <button
              disabled={loading}
              onClick={() => {
                setLoading(true);
                void refresh()
                  .then(() => setFeedback(null))
                  .catch((error) =>
                    setFeedback({ kind: "error", text: errorText(error) }),
                  )
                  .finally(() => setLoading(false));
              }}
            >
              Retry loading roster
            </button>
          )}
          <button
            aria-label="Dismiss message"
            onClick={() => setFeedback(null)}
          >
            ×
          </button>
        </div>
      )}
      {loading && <p role="status">Loading roster…</p>}
      {roster && (
        <>
          {mode === "assign" ? (
            <div className="roster-list-pool-tabs workflow-tabs" role="group" aria-label="Show CWL accounts">
              {(["all", "main", "lazy"] as const).map((pool) => (
                <button
                  type="button"
                  key={pool}
                  aria-pressed={listPool === pool}
                  disabled={uiLocked}
                  onClick={() => {
                    if (!mayLeaveEditor()) return;
                    setListPool(pool);
                    if (pool !== "all") setPoolFilter(pool);
                    setPreview(null);
                    setBulkDestination("");
                    setSelectedTags([]);
                    setSearch("");
                    setEditingTag(null);
                  }}
                >
                  {pool === "all" ? "All accounts" : pool === "main" ? "Main CWL" : "Lazy CWL"}
                </button>
              ))}
            </div>
          ) : (
            <CwlPoolTabs
              value={poolFilter}
              disabled={uiLocked}
              onChange={(pool) => {
                if (!mayLeaveEditor()) return;
                setPoolFilter(pool);
                setPreview(null);
                setBulkDestination("");
                setRuleTag("");
                setLeagues([]);
                setTownHalls([]);
                setSearch("");
                setEditingTag(null);
              }}
            />
          )}
          {season && canSignups && mode === "assign" && (
            <StaffSignupControls
              key={seasonId}
              disabled={busy || selectedTags.length > 0 || !!manualTag || !!editingTag || rulesDirty || weightsDirty}
              onOpenChange={setSignupOpen}
              season={season}
              onChanged={async () => {
                await refresh();
                await onSeasonRefresh?.();
              }}
              onDirty={setSignupDirty}
              onBusy={setSignupBusy}
            />
          )}
          {mode === "assign" ? (
            <div className="roster-assign-summary" role="status">
              <span><strong>{poolAccounts.length}</strong> signed up</span>
              <span><strong>{assigned}</strong> assigned</span>
              <span><strong>{poolAccounts.length - assigned}</strong> awaiting placement</span>
              <span><strong>{missingWeight}</strong> missing weight</span>
            </div>
          ) : (
          <div className="roster-overview">
            <div>
              <strong>{poolAccounts.length}</strong>
              <span>signed-up accounts</span>
            </div>
            <div>
              <strong>{assigned}</strong>
              <span>assigned</span>
            </div>
            <div>
              <strong>{poolAccounts.length - assigned}</strong>
              <span>unassigned</span>
            </div>
            <div>
              <strong>{missingWeight}</strong>
              <span>missing effective weight</span>
            </div>
          </div>
          )}
          {canRoster && <div
            className="roster-workflow-nav"
            role="group"
            aria-label="Roster workspace views"
          >
            {(
              [
                { id: "assign", label: "Assign accounts" },
                { id: "compare", label: "Compare clans" },
                { id: "rules", label: "Clan settings" },
                { id: "weights", label: `Weights · ${missingWeight} missing` },
              ] as const
            ).map((item) => (
              <button
                key={item.id}
                disabled={uiLocked}
                aria-pressed={mode === item.id}
                className={mode === item.id ? "active" : ""}
                onClick={() => {
                  if (item.id !== mode && !mayLeaveEditor()) return;
                  setMode(item.id);
                  setManualTag(null);
                  setSelectedTags([]);
                              }}
              >
                {item.label}
              </button>
            ))}
          </div>}
          <div className="roster-toolbar">
            <span>
              {mode === "assign" && !canRoster
                ? "Select accounts to change their signup type or remove saved signups."
                : mode === "assign" && viewPool === "all"
                  ? "Choose Main or Lazy CWL to preview automatic placements."
                : mode === "assign"
                ? `${poolAccounts.filter((account) => account.auto_placement_reason === "ready").length} ready for auto-placement · ${poolAccounts.filter((account) => account.auto_placement_reason && account.auto_placement_reason !== "ready").length} need attention`
                : mode === "compare"
                  ? "Compare up to 10 clans side by side."
                  : mode === "rules"
                    ? "Set clan capacity and automatic placement ranges."
                    : "Check missing weights and manage overrides."}
            </span>
            <button
              disabled={uiLocked}
              onClick={() => {
                if (mayLeaveEditor())
                  void refresh().catch((error) =>
                    setFeedback({ kind: "error", text: errorText(error) }),
                  );
              }}
            >
              Refresh
            </button>
            {canRoster && mode === "assign" && viewPool !== "all" && (
              <button
                disabled={uiLocked || archived || !activeClans.length}
                onClick={() => void previewPlacement()}
              >
                Auto-place preview
              </button>
            )}
            {canRoster && onReviewPublication && mode !== "assign" && (
              <button
                className="primary"
                disabled={busy}
                onClick={onReviewPublication}
              >
                Finalize both groups →
              </button>
            )}
          </div>
          {canRoster && mode === "weights" && (
            <WeightQueue
              onDirty={setWeightsDirty}
              onEdit={(tag) => {
                setFeedback(null);
                setEditingTag(tag);
              }}
              key={seasonId}
              accounts={poolAccounts}
              busy={busy}
              onRefresh={() => void refreshWeights()}
              onClose={() => {
                if (mayLeaveEditor()) setMode("assign");
              }}
              onSave={(tag, weight) =>
                edit(
                  tag,
                  { manual_weight: weight },
                  "Manual weight saved. Existing placement preserved.",
                )
              }
            />
          )}
          {canRoster && roster.undo && (
            <div className="roster-undo card">
              <div>
                <strong>Undo last placement change</strong>
                <small>{roster.undo.label}</small>
              </div>
              <button
                disabled={uiLocked || archived || roster.undo.revision !== roster.revision}
                onClick={() => void undoPlacement()}
              >
                Undo
              </button>
            </div>
          )}
          {canRoster && mode === "rules" && (
            <section id="clan-range-editor" className="roster-rules card">
              <div className="card-heading">
                <h2>Clan ranges & capacity</h2>
              </div>
              <p>
                Set this season’s weight range and capacity. Automatic placement
                uses these settings. Existing assignments stay unchanged.
              </p>
              {ruleClan ? (
                <>
                  <label>
                    Hosting clan
                    <select
                      value={ruleClan.tag}
                      onChange={(event) => {
                        if (mayLeaveEditor()) setRuleTag(event.target.value);
                      }}
                      disabled={busy}
                    >
                      {activeClans.map((clan) => (
                        <option key={clan.tag} value={clan.tag}>
                          {clan.name} ·{" "}
                          {clan.cwl_league || "League unavailable"} · {clan.tag}
                        </option>
                      ))}
                    </select>
                  </label>
                  <RuleForm
                    onDirty={setRulesDirty}
                    key={`${seasonId}-${ruleClan.tag}`}
                    clan={ruleClan}
                    busy={busy}
                    onSave={(rules) => saveRules(ruleClan, rules)}
                  />
                </>
              ) : (
                <p>Add a hosting clan in Seasons & clans first.</p>
              )}
            </section>
          )}
          {editingTag && roster.accounts.some((a) => a.tag === editingTag) && (
            <RosterPlayerDialog
              onDirty={setPlayerDirty}
              key={`${seasonId}:${editingTag}`}
              account={roster.accounts.find((a) => a.tag === editingTag)!}
              clans={roster.clans}
              busy={busy}
              error={feedback?.kind === "error" ? feedback.text : undefined}
              onClose={() => {
                if (!busy) setEditingTag(null);
              }}
              onSave={(body) => edit(editingTag, body, "Account updated.")}
              onRemove={() => removeSignup(editingTag)}
              archived={archived}
              onPoolChange={(pool) => bulkChangeSignups(pool, [editingTag])}
            />
          )}
          {canRoster && mode === "compare" && (
            <CompareClans
              key={`${seasonId}:${poolFilter}`}
              pool={poolFilter}
              seasonId={seasonId}
              roster={roster}
              busy={busy}
              onEdit={(tag) => {
                setFeedback(null);
                setEditingTag(tag);
              }}
            />
          )}
          {canRoster && mode === "assign" && preview && (
            <section
              className="card roster-preview"
              aria-labelledby="preview-title"
            >
              <div className="card-heading">
                <h2 id="preview-title">Automatic placement preview</h2>
                <button onClick={() => setPreview(null)}>Close preview</button>
              </div>
              <p>
                {preview.placements.length} proposed placement
                {preview.placements.length === 1 ? "" : "s"} ·{" "}
                {preview.unassigned.length} unresolved. Nothing changes until
                you apply this preview.
              </p>
              <div className="preview-columns">
                <div>
                  <h3>Proposed placements</h3>
                  <div className="preview-scroll">
                    {preview.placements.length ? (
                      preview.placements.map((item) => (
                        <div className="preview-line" key={item.tag}>
                          <strong>
                            {roster.accounts.find(
                              (account) => account.tag === item.tag,
                            )?.player_name || item.tag}
                          </strong>
                          <small>
                            {item.tag} → {clanName(item.assigned_clan_tag)}
                          </small>
                        </div>
                      ))
                    ) : (
                      <p>No accounts can be placed with the current rules.</p>
                    )}
                  </div>
                </div>
                <div>
                  <h3>Accounts still needing a clan</h3>
                  <div className="preview-scroll">
                    {preview.unassigned.length ? (
                      preview.unassigned.map((item) => (
                        <div className="preview-line" key={item.tag}>
                          <strong>
                            {roster.accounts.find(
                              (account) => account.tag === item.tag,
                            )?.player_name || item.tag}
                          </strong>
                          <small>
                            {item.tag} ·{" "}
                            {roster.accounts.find(
                              (account) => account.tag === item.tag,
                            )?.auto_placement_note || reasonText(item.reason)}
                          </small>
                        </div>
                      ))
                    ) : (
                      <p>None.</p>
                    )}
                  </div>
                </div>
              </div>
              <div className="roster-preview-actions">
                <button
                  className="primary"
                  disabled={
                    uiLocked || archived ||
                    !preview.placements.length ||
                    preview.revision !== roster.revision
                  }
                  onClick={() => void applyPlacement()}
                >
                  Apply reviewed placements
                </button>
              </div>
            </section>
          )}
          {mode === "assign" && (
            <>
              <div className="roster-account-tools">
              <div className="roster-quick-search">
                <label>
                  Find accounts
                  <input
                    value={search}
                    disabled={uiLocked}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Name, tag or Discord ID"
                  />
                </label>
                <label>
                  Show
                  <select
                    value={assignmentFilter}
                    disabled={uiLocked}
                    onChange={(event) =>
                      setAssignmentFilter(
                        event.target.value as "all" | "assigned" | "unassigned",
                      )
                    }
                  >
                    <option value="all">All accounts</option>
                    <option value="unassigned">Unassigned</option>
                    <option value="assigned">Assigned</option>
                  </select>
                </label>
                <label>
                  Sort
                  <select
                    value={sort}
                    disabled={uiLocked}
                    onChange={(event) =>
                      setSort(event.target.value as RosterSort)
                    }
                  >
                    <option value="name">Name A–Z</option>
                    <option value="town_hall_desc">TH: highest first</option>
                    <option value="town_hall_asc">TH: lowest first</option>
                    <option value="weight_desc">Weight: highest first</option>
                    <option value="weight_asc">Weight: lowest first</option>
                  </select>
                </label>
              </div>
              <details className="roster-more-filters">
                <summary>
                  Filters · League, Town Hall &amp; grouping{" "}
                  {readinessFilter !== "all" ||
                  leagues.length ||
                  townHalls.length || groupByDiscord
                    ? "· Active"
                    : ""}
                </summary>
                <label className="roster-group-toggle">
                  <input type="checkbox" checked={groupByDiscord}
                    disabled={uiLocked || !!manualTag || !!editingTag}
                    onChange={(event) => {
                      setGroupByDiscord(event.target.checked);
                      setPage(0);
                    }} />
                  Group by Discord user
                </label>
                <div className="card readiness-filter">
                  <label>
                    Readiness check
                    <select
                      value={readinessFilter}
                      disabled={uiLocked}
                      onChange={(event) => {
                        setReadinessFilter(
                          event.target.value as ReadinessFilter,
                        );
                        setSelectedTags([]);
                      }}
                    >
                      <option value="all">All accounts</option>
                      <option value="unassigned">Unassigned accounts</option>
                      <option value="missing_weight">Missing weights</option>
                      <option value="over_capacity">Clans over capacity</option>
                    </select>
                  </label>
                </div>
                <div className="clan-filter-bar">
                  <FilterPicker
                    label="League"
                    disabled={uiLocked}
                    options={[
                      ...new Set(
                        sortClans(roster.clans, "league_desc").map((clan) =>
                          leagueValue(clan.cwl_league),
                        ),
                      ),
                    ]}
                    selected={leagues}
                    onChange={(values) => {
                      setLeagues(values);
                      setSelectedTags([]);
                    }}
                  />
                  <FilterPicker
                    label="Town Halls"
                    disabled={uiLocked}
                    options={[
                      ...new Set(
                        roster.accounts.map((account) => account.town_hall),
                      ),
                    ]
                      .sort((a, b) => (b ?? -1) - (a ?? -1))
                      .map((value) =>
                        value == null ? "Unknown TH" : `TH ${value}`,
                      )}
                    selected={townHalls}
                    onChange={(values) => {
                      setTownHalls(values);
                      setSelectedTags([]);
                    }}
                  />
                  <button
                    disabled={uiLocked}
                    onClick={() => {
                      setGroupByDiscord(false);
                      setLeagues([]);
                      setTownHalls([]);
                      setSearch("");
                      setAssignmentFilter("all");
                      setReadinessFilter("all");
                      setSelectedTags([]);
                    }}
                  >
                    Clear filters
                  </button>
                  <small>
                    {filtered.length} of {poolAccounts.length} accounts shown.
                    League filters use the assigned clan; unassigned accounts
                    have no league.
                  </small>
                </div>
              </details>
              </div>
              <div className="roster-list-heading" ref={listHeading} tabIndex={-1}>
                <label className="roster-select-all">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    disabled={uiLocked || archived || (!canRoster && !canSignups) || (!canSignups && viewPool === "all") || !visibleTags.length || (!allVisibleSelected && selectingPageWouldExceedLimit)}
                    onChange={(event) =>
                      setSelectedTags(
                        event.target.checked
                          ? [
                              ...new Set([...selectedTags, ...visibleTags]),
                            ]
                          : selectedTags.filter(
                              (tag) => !visibleTags.includes(tag),
                            ),
                      )
                    }
                  />{" "}
                  Select all {visibleTags.length} on this page
                </label>
                <span>
                  {selectingPageWouldExceedLimit && !allVisibleSelected
                    ? "Select up to 50 accounts; clear some before selecting this page."
                    : `${filtered.length} matching · ${selectedTags.length} selected`}
                </span>
              </div>
              {selectedTags.length > 0 && (
                <div className="roster-bulk card roster-selection-bar">
                  <strong>{selectedTags.length}/50 selected{hiddenSelection ? ` · ${hiddenSelection} on other pages` : ""}</strong>
                  {canRoster && viewPool !== "all" && !signupReviewOpen && (
                    <div className="roster-placement-bulk">
                      <label>
                        Hosting clan
                        <select
                          value={bulkDestination}
                          disabled={working || archived}
                          onChange={(event) => setBulkDestination(event.target.value)}
                        >
                          <option value="">Choose a destination</option>
                          <option value="__unassign__">Unassign selected</option>
                          <ClanDestinationOptions clans={roster.clans} pool={poolFilter} />
                        </select>
                      </label>
                      <button
                        className="primary"
                        disabled={working || archived || !!staleSelection || selectedTags.length > 50 || !bulkDestination}
                        onClick={() => void bulkAssign()}
                      >
                        {bulkDestination === "__unassign__" ? `Unassign ${selectedTags.length}` : `Assign ${selectedTags.length}`}
                      </button>
                    </div>
                  )}
                  {canRoster && viewPool === "all" && !canSignups && (
                    <small>Choose Main or Lazy CWL above to bulk assign placements.</small>
                  )}
                  {canSignups && !archived && (
                    <RosterSignupActions
                      key={roster.revision}
                      accounts={selectedAccounts}
                      clans={roster.clans}
                      error={feedback?.kind === "error" ? feedback.text : undefined}
                      busy={working || !!staleSelection || selectedTags.length > 50}
                      onApply={bulkChangeSignups}
                      onReviewChange={setSignupReviewOpen}
                    />
                  )}
                  {staleSelection > 0 && <small role="alert">Roster changed. Clear selection and choose accounts again.</small>}
                  <button disabled={working || signupReviewOpen} onClick={() => setSelectedTags([])}>Clear selection</button>
                </div>
              )}
              {groupByDiscord && groupNamesError && (
                <p role="status">Discord profiles could not be loaded. Accounts remain grouped by Discord ID.
                  <button type="button" onClick={() => setGroupNamesRetry(value => value + 1)}>Retry profiles</button>
                </p>
              )}
              {filtered.length ? (
                <div className="roster-account-list">
                  {pageAccounts.map((account, index) => (
                    <Fragment key={account.tag}>
                    {groupByDiscord && (index === 0 || rosterMemberKey(pageAccounts[index - 1]) !== rosterMemberKey(account)) && (
                      <header className="roster-member-heading">
                        <RosterDiscordIdentity userId={account.user_id} resolvedMember={groupMembers[account.user_id] || null} resolving={groupNamesLoading} />
                        <small>{pageAccounts.filter(item => rosterMemberKey(item) === rosterMemberKey(account)).length} accounts shown</small>
                      </header>
                    )}
                    <article
                      className={`card roster-account ${account.assigned_clan_tag ? "roster-account-assigned" : ""} ${account.outside_family_and_hosts ? "roster-account-outside" : ""} ${selectedTags.includes(account.tag) ? "roster-account-selected" : ""}`}
                      key={account.tag}
                    >
                      <div className="roster-account-head">
                        <label className="roster-account-select">
                          <input
                            type="checkbox"
                            aria-label={`Select ${account.player_name} for bulk actions`}
                            checked={selectedTags.includes(account.tag)}
                            disabled={
                              uiLocked || archived || (!canSignups && viewPool === "all") ||
                              (!selectedTags.includes(account.tag) &&
                                selectedTags.length >= 50)
                            }
                            onChange={() => toggleSelected(account.tag)}
                          />
                        </label>
                        <div>
                          <h3>
                            <TownHallIcon level={account.town_hall} />
                            {account.player_name}
                          </h3>
                          <small>
                            {account.tag} · TH {account.town_hall ?? "—"}{viewPool === "all" ? ` · ${account.pool === "main" ? "Main" : "Lazy"} CWL` : ""}
                          </small>
                        </div>
                      </div>
                      <div className="roster-row-summary">
                        <span className="roster-row-weight" aria-label={`Weight: ${weightText(account.effective_weight)}`}>
                          <small>Weight</small>
                          <strong>
                            {weightText(account.effective_weight)}
                          </strong>
                        </span>
                        <div className="roster-row-clans">
                          <span className="roster-row-host">
                            <small>Hosting clan</small>
                            <strong>
                              {account.kept && (
                                <span className="roster-placement-lock" role="img" aria-label="Locked placement: auto-place will not move this account" title="Locked placement: auto-place will not move this account">
                                  <DashboardIcon name="locked" />
                                </span>
                              )}
                              {clanName(account.assigned_clan_tag)}
                            </strong>
                          </span>
                          <span className="roster-current-clan">
                            <small>
                              Current clan
                              {account.current_clan_status === "stale"
                                ? " · Last checked"
                                : ""}
                            </small>
                            <strong>
                              {account.current_clan_status === "unavailable" ||
                              !account.current_clan_status
                                ? "Unavailable"
                                : account.current_clan_name ||
                                  account.current_clan_tag ||
                                  "No clan"}
                            </strong>
                            {account.outside_family_and_hosts && (
                              <small className="roster-outside-label">Outside family / hosting clans</small>
                            )}
                          </span>
                        </div>
                        {!account.assigned_clan_tag && (account.kept || account.auto_placement_reason !== "ready") && (
                          <span className="roster-row-status">
                            {account.kept ? "Held unassigned · unlock in Details to auto-place" : account.auto_placement_note || "Not assigned"}
                          </span>
                        )}
                      </div>
                      <div className="roster-placement-help">
                        {canRoster && <button
                          disabled={uiLocked || archived}
                          onClick={() => {
                            setManualTag(account.tag);
                            setManualClan(account.assigned_clan_tag || "");
                            setFeedback(null);
                          }}
                        >
                          {account.assigned_clan_tag
                            ? "Move →"
                            : "Assign →"}
                        </button>}
                        <button
                          type="button"
                          disabled={uiLocked}
                          aria-label={`Details for ${account.player_name}`}
                          onClick={() => {
                            setFeedback(null);
                            setEditingTag(account.tag);
                          }}
                        >
                          Details
                        </button>
                      </div>
                      {canRoster && manualTag === account.tag && (
                        <form
                          className="roster-manual-place"
                          onSubmit={(event) => {
                            event.preventDefault();
                            if (!manualClan) return;
                            void edit(
                              account.tag,
                              { assigned_clan_tag: manualClan, kept: true },
                              `${account.player_name} assigned to ${clanName(manualClan)}.`,
                            ).then((saved) => {
                              if (saved) setManualTag(null);
                            });
                          }}
                        >
                          <label>
                            Place {account.player_name} in
                            <select
                              autoFocus
                              value={manualClan}
                              disabled={busy}
                              onChange={(event) =>
                                setManualClan(event.target.value)
                              }
                            >
                              <option value="">Choose a hosting clan</option>
                              <ClanDestinationOptions
                                clans={roster.clans}
                                pool={account.pool}
                                current={account.assigned_clan_tag}
                              />
                            </select>
                          </label>
                          <p>
                            {account.pool === "lazy"
                              ? "Choose a Lazy host with space."
                              : "Choose an active hosting clan with space."}
                          </p>
                          {feedback?.kind === "error" && (
                            <p role="alert">{feedback.text}</p>
                          )}
                          <button
                            type="submit"
                            className="primary"
                            disabled={busy || !manualClan}
                          >
                            {busy ? "Saving…" : "Save placement"}
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => setManualTag(null)}
                          >
                            Cancel
                          </button>
                        </form>
                      )}
                    </article>
                    </Fragment>
                  ))}
                </div>
              ) : (
                <div className="card empty">
                  <p>No accounts match these filters.</p>
                </div>
              )}
              {accountPages.length > 1 && (
                <nav className="roster-pagination" aria-label="Account pages">
                  <button
                    disabled={uiLocked || currentPage === 0}
                    onClick={() => {
                      setPage(currentPage - 1);
                      listHeading.current?.scrollIntoView({ block: "start" });
                    }}
                  >
                    ← Previous
                  </button>
                  <span>
                    Page {currentPage + 1} of {lastPage + 1}
                  </span>
                  <button
                    disabled={uiLocked || currentPage === lastPage}
                    onClick={() => {
                      setPage(currentPage + 1);
                      listHeading.current?.scrollIntoView({ block: "start" });
                    }}
                  >
                    Next →
                  </button>
                </nav>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
function reasonText(reason: string) {
  const labels: Record<string, string> = {
    kept: "Kept placement",
    missing_weight: "Missing weight",
    source_unavailable: "Weight source unavailable",
    no_eligible_rule: "No matching hosting rule",
    full: "Matching clans are full",
  };
  return labels[reason] || reason.replaceAll("_", " ");
}
function RuleForm({
  clan,
  busy,
  onSave,
  onDirty,
}: {
  onDirty: (dirty: boolean) => void;
  clan: RosterClan;
  busy: boolean;
  onSave: (rules: {
    pool: Pool;
    capacity: number;
    min_weight: number | null;
    max_weight: number | null;
    lower_league: boolean | null;
  }) => Promise<boolean>;
}) {
  const [pool, setPool] = useState<Pool | "">(clan.pool ?? "");
  const [capacity, setCapacity] = useState(
    clan.capacity === null ? "" : String(clan.capacity),
  );
  const [minWeight, setMinWeight] = useState(weightInputText(clan.min_weight));
  const [maxWeight, setMaxWeight] = useState(weightInputText(clan.max_weight));
  const [error, setError] = useState("");
  const values = {
    pool: clan.pool ?? "",
    capacity: clan.capacity === null ? "" : String(clan.capacity),
    minWeight: weightInputText(clan.min_weight),
    maxWeight: weightInputText(clan.max_weight),
  };
  const [base, setBase] = useState(values);
  const changed =
    pool !== base.pool ||
    capacity !== base.capacity ||
    minWeight !== base.minWeight ||
    maxWeight !== base.maxWeight;
  const stale = JSON.stringify(base) !== JSON.stringify(values);
  const useLatest = () => {
    setPool(clan.pool ?? "");
    setCapacity(values.capacity);
    setMinWeight(values.minWeight);
    setMaxWeight(values.maxWeight);
    setBase(values);
  };
  useEffect(() => {
    if (!changed && stale) useLatest();
  }, [clan, changed, stale]);
  useEffect(() => {
    onDirty(changed);
    return () => onDirty(false);
  }, [changed, onDirty]);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || stale) return;
    try {
      const min = parseWeightK(minWeight);
      const max = parseWeightK(maxWeight);
      if (min !== null && max !== null && min >= max)
        throw new Error("Maximum weight must be greater than minimum weight.");
      const size = Number(capacity);
      if (!pool) throw new Error("Choose a signup pool for this hosting clan.");
      if (capacity === "" || (size !== 15 && size !== 30))
        throw new Error("Capacity must be 15 or 30.");
      setError("");
      if (
        await onSave({
          pool,
          capacity: size,
          min_weight: min,
          max_weight: max,
          lower_league: clan.lower_league,
        })
      )
        setBase({ pool, capacity, minWeight, maxWeight });
    } catch (error) {
      setError(errorText(error));
    }
  };
  return (
    <form className="roster-rule-form" onSubmit={submit}>
      <fieldset disabled={busy}>
        <div className="card-heading">
          <h3>{clan.name}</h3>
          <span className="badge">
            {clan.assigned_count}/{clan.capacity ?? "—"} assigned
          </span>
        </div>
        <small>{clan.tag}</small>
        <div className="rule-fields">
          <label>
            Signup pool
            <select
              value={pool}
              onChange={(event) => setPool(event.target.value as Pool)}
            >
              <option value="">Not set</option>
              <option value="main">Main Clan CWL</option>
              <option value="lazy">Lazy CWL</option>
            </select>
          </label>
          <label>
            Capacity
            <select
              value={capacity}
              onChange={(event) => setCapacity(event.target.value)}
            >
              <option value="">Not set</option>
              <option value="15">15</option>
              <option value="30">30</option>
            </select>
          </label>
          <label>
            Minimum weight (k, included)
            <input
              type="number"
              min="0"
              step="0.001"
              value={minWeight}
              onChange={(event) => setMinWeight(event.target.value)}
              placeholder="No minimum"
            />
          </label>
          <label>
            Maximum weight (k, excluded)
            <input
              type="number"
              min="0"
              step="0.001"
              value={maxWeight}
              onChange={(event) => setMaxWeight(event.target.value)}
              placeholder="No maximum"
            />
          </label>
        </div>
        <p className="small">
          Enter weights in thousands: 160 means 160,000. Leave either end blank
          for no limit. The maximum is excluded, so 160–174 includes 160k up to
          just below 174k.
        </p>
        {error && (
          <p className="inline-reason" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy || stale || !changed}>
          Save clan range & rules
        </button>
        {stale && changed && (
          <p role="alert">
            Clan settings changed elsewhere. Your edits are preserved.
            <button type="button" disabled={busy} onClick={useLatest}>
              Discard edits and use latest settings
            </button>
          </p>
        )}
      </fieldset>
    </form>
  );
}
