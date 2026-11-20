import { searchInputProps } from "./inputProps";
import { SectionTabPanel } from "./SectionTabs";
import EmptyState from "./EmptyState";
import { monthSeasons, seasonMonthLabel } from "./seasonLabels";
import LoadError from "./LoadError";
import CwlPageHeader from "./CwlPageHeader";
import { Button } from "./rosterUi/primitives";
import BonusHelpPanel from "./BonusHelpPanel";
import useConfirmDialog from "./useConfirmDialog";
import { exportMonthLabel } from "./exportPreview";
import ActionMenu from "./rosterUi/ActionMenu";
import ActionPanel from "./ActionPanel";
import ListToolbar from "./rosterUi/ListToolbar";
import FiltersTrigger from "./rosterUi/FiltersTrigger";
import SortTrigger from "./rosterUi/SortTrigger";
import RosterMenu from "./rosterUi/Menu";
import "./ParticipationWorkspace.css";
import CwlPoolTabs, { useCwlPool } from "./CwlPoolTabs";
import FilterChips from "./FilterChips";
import BonusStepBar from "./BonusStepBar";
import ParticipationRecord from "./ParticipationRecord";
import BonusClanSelect from "./BonusClanSelect";
import ResultsSettingsSheet, {
  type SettingsSaved,
} from "./ResultsSettingsSheet";
import useUnsavedWork from "./useUnsavedWork";
import useInfractions from "./useInfractions";
import { useDashboardPermission } from "./DashboardPermissions";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Pool, type Season } from "./api";
import { loadBonusStatus, type BonusStatus } from "./bonusStatus";
import LazyAnnouncementCard from "./LazyAnnouncementCard";
import {
  countText,
  matchesOutcome,
  outcomeCounts,
  outcomeLabels,
  outcomeOrder,
  resultTimeText,
  type OutcomeFilter,
} from "./participationOutcome";
import {
  parseResultsState,
  resultsStateQuery,
  type ResultsSort,
} from "./resultsUrlState";
import {
  visibleParticipation,
  participationSummary,
  type ParticipationAccount,
  type ParticipationData,
  type ParticipationSync,
} from "./participation";

type Props = {
  seasonId: string;
  seasons: Season[];
  onDirty?: (dirty: boolean) => void;
  /** Opens the bonus steps with pool, clan and step keys; absent without bonus access. */
  onBonus?: (state?: string) => void;
  onSeasonChange: (id: string) => void;
  /** Opens Strikes on one player; absent without strike add access. */
  onAddStrike?: (tag: string) => void;
  urlState?: string;
  onUrlState?: (state: string, push: boolean) => void;
};

const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Results could not be loaded. Try again.";

export default function ParticipationWorkspace({
  seasonId,
  seasons,
  onSeasonChange,
  onDirty: reportDirty,
  onBonus,
  onAddStrike,
  urlState = "",
  onUrlState,
}: Props) {
  const initial = useRef(parseResultsState(urlState));
  const [data, setData] = useState<ParticipationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{
    text: string;
    kind: "success" | "error" | "info";
  } | null>(null);
  const [dirtyTags, setDirtyTags] = useState<Set<string>>(new Set());
  const [activeEditorTag, setActiveEditorTag] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const settingsTrigger = useRef<HTMLElement | null>(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const syncPending = useRef(false);
  const [syncError, setSyncError] = useState("");
  const [recordEpoch, setRecordEpoch] = useState(0);
  const [search, setSearch] = useState("");
  const [listPanel, setListPanel] = useState<"filters" | "sort" | null>(null);
  const [listTrigger, setListTrigger] = useState<HTMLElement | null>(null);
  const [storedPool, setStoredPool] = useCwlPool();
  const [urlPool, setUrlPool] = useState<Pool | undefined>(
    initial.current.pool,
  );
  const pool = urlPool || storedPool;
  const [clan, setClan] = useState(initial.current.clan || "all");
  const [outcome, setOutcome] = useState<OutcomeFilter>(
    initial.current.outcome || "all",
  );
  const [sort, setSort] = useState<ResultsSort>(initial.current.sort || "name");
  const filterKey = JSON.stringify([
    search,
    pool,
    clan,
    sort,
    outcome,
    seasonId,
  ]);
  const [renderLimit, setRenderLimit] = useState({ key: filterKey, count: 50 });
  const [status, setStatus] = useState<BonusStatus | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [statusError, setStatusError] = useState("");
  const statusRequest = useRef(0);
  const statusEnabled = useRef(!!onBonus);
  statusEnabled.current = !!onBonus;
  const emitted = useRef(urlState);
  const requestId = useRef(0);
  const currentSeason = useRef(seasonId);
  currentSeason.current = seasonId;
  const loadedSeason = useRef<string | null>(null);
  const archived =
    seasons
      .find((season) => String(season.id) === seasonId)
      ?.status.toLowerCase() === "archived";
  const infractions = useInfractions(
    seasonId,
    useDashboardPermission("cwl_bonuses"),
    !!archived,
    status,
    () => {
      // Sit-out markers and clan counts both follow the saved staff exception.
      void load();
    },
  );
  const editing = activeEditorTag !== null;
  const controlsLocked = editing || syncBusy || loading;
  const writesLocked = controlsLocked || !!error;
  // An open sheet locks the list and other records, never its own record.
  const ownRecordLocked = syncBusy || loading || !!error;
  const { confirm, dialog: confirmation } = useConfirmDialog(
    `${seasonId}:${controlsLocked}:${archived}:${error}`,
  );
  useUnsavedWork(dirtyTags.size > 0 || settingsDirty || syncBusy, reportDirty);

  const emit = (
    next: {
      pool?: Pool;
      clan?: string;
      outcome?: OutcomeFilter;
      sort?: ResultsSort;
    },
    push = true,
  ) => {
    const query = resultsStateQuery({
      pool: next.pool ?? pool,
      clan: (next.clan ?? clan) === "all" ? undefined : (next.clan ?? clan),
      outcome: next.outcome ?? outcome,
      sort: next.sort ?? sort,
    });
    emitted.current = query;
    onUrlState?.(query, push);
  };
  const choosePool = (next: Pool) => {
    setStoredPool(next);
    setUrlPool(next);
  };
  // Back, Forward and shared links restore the list state.
  useEffect(() => {
    if (urlState === emitted.current) return;
    emitted.current = urlState;
    const next = parseResultsState(urlState);
    if (next.pool) choosePool(next.pool);
    setClan(next.clan || "all");
    setOutcome(next.outcome || "all");
    setSort(next.sort || "name");
  }, [urlState]);

  const onDirty = useCallback(
    (tag: string, dirty: boolean) =>
      setDirtyTags((current) => {
        if (current.has(tag) === dirty) return current;
        const next = new Set(current);
        if (dirty) next.add(tag);
        else next.delete(tag);
        return next;
      }),
    [],
  );
  const clearProtected = () => {
    setData(null);
    setSettingsOpen(false);
    setNotice(null);
    setActiveEditorTag(null);
    setDirtyTags(new Set());
  };
  const loadStatus = useCallback(async (sid: string) => {
    const id = ++statusRequest.current;
    setStatusFailed(false);
    setStatusError("");
    try {
      const result = await loadBonusStatus(sid);
      if (id !== statusRequest.current || currentSeason.current !== sid) return;
      setStatus(result);
    } catch (cause) {
      if (id !== statusRequest.current || currentSeason.current !== sid) return;
      setStatus(null);
      setStatusFailed(true);
      setStatusError(cause instanceof Error ? cause.message : "");
    }
  }, []);
  const load = useCallback(async () => {
    if (!seasonId) return;
    const sid = seasonId;
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const result = await api<ParticipationData>(
        `/seasons/${encodeURIComponent(sid)}/participation`,
      );
      if (id !== requestId.current || currentSeason.current !== sid) return;
      setData(result);
      // The step bar reads after the list, so it never delays the players.
      if (statusEnabled.current) void loadStatus(sid);
    } catch (cause) {
      if (id !== requestId.current || currentSeason.current !== sid) return;
      setError(errorText(cause));
      if (cause instanceof ApiError && [401, 403].includes(cause.status))
        clearProtected();
    } finally {
      if (id === requestId.current && currentSeason.current === sid)
        setLoading(false);
    }
  }, [seasonId, loadStatus]);
  useEffect(() => {
    requestId.current += 1;
    statusRequest.current += 1;
    clearProtected();
    setStatus(null);
    setStatusFailed(false);
    setError("");
    setSyncError("");
    setSearch("");
    // A season change starts a new list; the first visit keeps the URL state.
    if (loadedSeason.current !== null && loadedSeason.current !== seasonId) {
      setClan("all");
      setOutcome("all");
      setSort("name");
      const query = resultsStateQuery({ pool });
      emitted.current = query;
      onUrlState?.(query, false);
    }
    loadedSeason.current = seasonId;
    if (seasonId) void load();
    return () => {
      requestId.current += 1;
    };
  }, [seasonId, load]);
  useEffect(() => {
    setRenderLimit((current) =>
      current.key === filterKey ? current : { key: filterKey, count: 50 },
    );
  }, [filterKey]);

  const changeSeason = async (id: string) => {
    if (controlsLocked || id === seasonId) return;
    if (
      dirtyTags.size &&
      !(await confirm(
        `Discard unsaved participation changes and open another season?`,
        "Discard and change season",
      ))
    )
      return;
    setDirtyTags(new Set());
    onSeasonChange(id);
  };
  const refreshList = async () => {
    if (controlsLocked) return;
    if (
      dirtyTags.size &&
      !(await confirm(
        "Discard unsaved participation changes and refresh?",
        "Discard and refresh",
      ))
    )
      return;
    if (dirtyTags.size) {
      setDirtyTags(new Set());
      setRecordEpoch((current) => current + 1);
    }
    setSyncError("");
    void load();
  };
  // The sheet saved a setting: reload what it can change.
  const settingsSaved = async (saved: SettingsSaved) => {
    if (saved.kind === "odds") {
      await load();
      return;
    }
    if (saved.cycleChanged) {
      setData(null);
      setDirtyTags(new Set());
      setRecordEpoch((current) => current + 1);
    }
    await load();
    setNotice({
      kind: "success",
      text: saved.enabled
        ? "Automatic CWL capture enabled."
        : "Automatic CWL capture disabled. You can still check manually.",
    });
  };
  const openSettings = () => {
    settingsTrigger.current = document.querySelector<HTMLElement>(
      ".participation-capture .roster-action-trigger",
    );
    setSettingsOpen(true);
  };
  const syncNow = async () => {
    if (
      !seasonId ||
      syncBusy ||
      syncPending.current ||
      editing ||
      dirtyTags.size ||
      archived ||
      error ||
      !data?.sync?.cycle
    )
      return;
    const sid = seasonId;
    syncPending.current = true;
    setSyncBusy(true);
    setSyncError("");
    try {
      const result = await api<{
        sync: ParticipationSync;
        updated_accounts: number;
      }>(`/seasons/${encodeURIComponent(sid)}/participation/sync`, "POST");
      if (currentSeason.current !== sid) return;
      setNotice({
        kind: "info",
        text: `CWL check finished. ${result.updated_accounts} current signup accounts updated. Review the status for this view below.`,
      });
    } catch (cause) {
      if (currentSeason.current === sid) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          clearProtected();
        setSyncError(errorText(cause));
      }
    } finally {
      if (currentSeason.current === sid) await load();
      syncPending.current = false;
      setSyncBusy(false);
    }
  };
  const resetToSource = async (
    account: ParticipationAccount,
  ): Promise<ParticipationAccount> => {
    const sid = seasonId;
    if (error) throw new Error("Refresh the results list before editing.");
    try {
      const result = await api<{ account: ParticipationAccount }>(
        `/seasons/${encodeURIComponent(sid)}/participation/${encodeURIComponent(account.tag)}/reset-to-source`,
        "POST",
        {
          revision: account.revision,
          publication_version: data?.publication_version ?? 0,
          roster_token: account.roster_token,
          source_checked_at: account.source_checked_at ?? null,
        },
      );
      if (currentSeason.current === sid) {
        setData((current) =>
          current
            ? {
                ...current,
                accounts: current.accounts.map((row) =>
                  row.tag === account.tag ? result.account : row,
                ),
              }
            : current,
        );
        setNotice({
          kind: "success",
          text: `${account.player_name} now uses synced values. Staff notes were kept.`,
        });
      }
      return result.account;
    } catch (cause) {
      if (currentSeason.current === sid) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          clearProtected();
        if (cause instanceof ApiError && cause.status === 409) {
          setNotice({
            kind: "error",
            text: "Source or roster changed. Latest records loaded; review before retrying.",
          });
          await load();
        }
      }
      throw cause;
    }
  };
  const save = async (
    account: ParticipationAccount,
    revision: number,
    publicationVersion: number | null,
    sourceCheckedAt: string | null,
    notes: string,
  ): Promise<ParticipationAccount> => {
    const sid = seasonId;
    if (error) throw new Error("Refresh the results list before editing.");
    try {
      const result = await api<{ account: ParticipationAccount }>(
        `/seasons/${encodeURIComponent(sid)}/participation/${encodeURIComponent(account.tag)}`,
        "PATCH",
        {
          revision,
          publication_version: publicationVersion ?? 0,
          roster_token: account.roster_token,
          source_checked_at: sourceCheckedAt,
          notes,
        },
      );
      if (currentSeason.current === sid) {
        setData((current) =>
          current
            ? {
                ...current,
                accounts: current.accounts.map((row) =>
                  row.tag === account.tag ? result.account : row,
                ),
              }
            : current,
        );
        setNotice({
          kind: "success",
          text: `${account.player_name} notes saved.`,
        });
      }
      return result.account;
    } catch (cause) {
      if (currentSeason.current === sid) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          clearProtected();
        if (cause instanceof ApiError && cause.status === 409) {
          setNotice({
            kind: "error",
            text: "This record or assignment changed elsewhere. Latest records loaded; review before saving again.",
          });
          await load();
        }
      }
      throw cause;
    }
  };

  const mainMinimum = status?.main_minimum ?? null;
  const ruleShown = pool === "lazy" || mainMinimum !== null;
  const activeOutcome = ruleShown ? outcome : "all";
  const poolAccounts = (data?.accounts || []).filter(
    (account) => account.pool === pool,
  );
  const clans = [
    ...new Map(
      poolAccounts
        .filter((account) => account.assigned_clan_tag)
        .map((account) => [
          account.assigned_clan_tag!,
          account.assigned_clan_name || account.assigned_clan_tag!,
        ]),
    ).entries(),
  ].sort((left, right) => left[1].localeCompare(right[1]));
  const filtered = visibleParticipation(data?.accounts || [], {
    search,
    pool,
    clan,
    sort,
  });
  const counts = outcomeCounts(filtered, mainMinimum);
  const visible = filtered.filter((account) =>
    matchesOutcome(account, activeOutcome, mainMinimum),
  );
  // A new filter starts at50 on its first render, before the reset effect runs.
  const requestedCount = renderLimit.key === filterKey ? renderLimit.count : 50;
  const shown = visible.slice(0, requestedCount);
  const visibleTags = new Set(shown.map((account) => account.tag));
  // Keep dirty/busy or open records mounted even when outside the visible slice.
  // Clean offscreen records can remount from the saved parent data.
  const sorted = visibleParticipation(data?.accounts || [], {
    search: "",
    pool: "all",
    clan: "all",
    sort,
  });
  const statusSummary = participationSummary(visible, data?.sync);
  const poolLabel = pool === "main" ? "Main CWL" : "Lazy CWL";
  // Opening the steps leaves this list, so unsaved result edits are confirmed first.
  const openSteps = async (query: string) => {
    if (!onBonus || controlsLocked) return;
    if (
      dirtyTags.size &&
      !(await confirm(
        "Discard unsaved participation changes and open the bonus steps?",
        "Discard and continue",
      ))
    )
      return;
    onBonus(query);
  };
  // The steps page names the step once its data loads, so the status read
  // and the open step never disagree.
  const stepsQuery = (tag: string) =>
    resultsStateQuery({ pool, clan: tag, view: "steps" });
  const checkNowBlocked =
    writesLocked || !!dirtyTags.size || archived || !data?.sync?.cycle;
  const chooseClan = (next: string) => {
    if (next === clan) return;
    if (onBonus && next !== "all") {
      void openSteps(stepsQuery(next));
      return;
    }
    setClan(next);
    emit({ clan: next });
  };
  // Clan options come from the status read; the list's own clans stand in until it loads.
  const clanChoices = status
    ? status.pools[pool].map((host) => ({ tag: host.tag, name: host.name }))
    : clans.map(([tag, name]) => ({ tag, name }));

  return (
    <div className="participation-workspace roster-ui page-wide">
      {confirmation}
      <CwlPageHeader
        className="participation-page-head"
        title={<h1>Results &amp; bonuses</h1>}
        help={<BonusHelpPanel />}
      >
        <RosterMenu
          label="Season"
          value={seasonId}
          disabled={controlsLocked}
          onValueChange={(next) => void changeSeason(next)}
          options={[
            { value: "", label: "Select a season" },
            ...monthSeasons(seasons).map((season) => ({
              value: String(season.id),
              label: seasonMonthLabel(season),
            })),
          ]}
        />
      </CwlPageHeader>
      {/* The step bar tracks one hosting clan; with all clans it has no state. */}
      {seasonId && onBonus && clan !== "all" && (
        <BonusStepBar
          seasonId={seasonId}
          pool={pool}
          clan={clan}
          status={status}
          failed={statusFailed}
          onRetry={() => void loadStatus(seasonId)}
          canOpen={(step) => step === "results" || !!onBonus}
          onSelect={(step, query) => {
            if (step !== "results") {
              void openSteps(query);
              return;
            }
            const next = parseResultsState(query);
            if (next.pool) choosePool(next.pool);
            setClan(next.clan || "all");
            emit({ pool: next.pool, clan: next.clan || "all" });
          }}
        />
      )}
      {!seasonId && <p>Select a season to view participation records.</p>}
      {error && (
        <div className="notice error" role="alert">
          Results could not be refreshed.{" "}
          {data && "Existing values may be out of date; edits are paused. "}
          {error}
          <button
            type="button"
            disabled={loading || editing}
            onClick={refreshList}
          >
            Retry
          </button>
        </div>
      )}
      {notice && (
        <div
          className={`notice ${notice.kind}`}
          role={notice.kind === "error" ? "alert" : "status"}
        >
          {notice.text}
        </div>
      )}
      {loading && !data && <p role="status">Loading results…</p>}
      {data && (
        <>
          <section
            className="participation-capture"
            aria-label="CWL capture status"
          >
            <div className="participation-capture-main">
              <p className="participation-capture-line">
                <strong>
                  {data.sync?.enabled ? "Capture on" : "Capture off"}
                </strong>{" "}
                ·{" "}
                {data.sync?.cycle
                  ? exportMonthLabel(data.sync.cycle)
                  : "CWL month not set"}{" "}
                · {statusSummary.label} ·{" "}
                {data.sync?.last_checked_at ? (
                  <time dateTime={data.sync.last_checked_at}>
                    {resultTimeText(data.sync.last_checked_at)}
                  </time>
                ) : (
                  "Not checked yet"
                )}
              </p>
              <ActionMenu
                name="CWL capture"
                disabled={controlsLocked}
                items={[
                  {
                    id: "check",
                    label: "Check Clash now",
                    disabled: checkNowBlocked,
                    onAction: () => void syncNow(),
                  },
                  {
                    id: "refresh",
                    label: "Refresh",
                    onAction: () => void refreshList(),
                  },
                  {
                    id: "settings",
                    label: "Settings",
                    onAction: openSettings,
                  },
                ]}
              />
            </div>
            {!data.sync?.enabled && (
              <p className="participation-capture-warning" role="status">
                Automatic CWL capture is off. Enable it in Settings to retain
                current results.
              </p>
            )}
            {statusSummary.warning && (
              <p className="participation-capture-warning" role="status">
                {statusSummary.warning}&nbsp;·{" "}
                <button
                  type="button"
                  className="participation-inline-action"
                  disabled={controlsLocked || checkNowBlocked}
                  onClick={() => void syncNow()}
                >
                  Check Clash now
                </button>
              </p>
            )}
            {syncError && (
              <p className="participation-capture-warning" role="alert">
                {syncError}
              </p>
            )}
            {!data.sync?.cycle && (
              <p className="participation-capture-warning">
                Set the CWL month in Settings before checking Clash ·{" "}
                <button
                  type="button"
                  className="participation-inline-action"
                  disabled={controlsLocked}
                  onClick={openSettings}
                >
                  Open Settings
                </button>
              </p>
            )}
          </section>
          {archived && (
            <div className="notice">
              Archived season · Results are read only.
            </div>
          )}
          <SectionTabPanel
            id="participation-pools"
            value={pool}
            enabled={false}
          >
            {clanChoices.length > 0 && (
              <BonusClanSelect
                clans={clanChoices}
                selected={clan}
                pool={pool}
                status={status}
                opensSteps={!!onBonus}
                disabled={controlsLocked}
                onChange={chooseClan}
              />
            )}
            {/* Bonuses access opens the steps; the send itself needs cwl_send. */}
            {pool === "lazy" && onBonus && status && (
              <LazyAnnouncementCard
                seasonId={seasonId}
                clans={status.pools.lazy}
                clanTag={clan === "all" ? "" : clan}
                archived={!!archived}
                disabled={controlsLocked}
                onSent={() => void loadStatus(seasonId)}
              />
            )}
            {pool === "lazy" && onBonus && clan === "all" && statusFailed && (
              <LoadError
                message={statusError || "Lazy announcement could not load."}
                onRetry={() => void loadStatus(seasonId)}
              />
            )}
            <div className="participation-toolbar">
              <label>
                Find a player
                <input
                  {...searchInputProps}
                  type="search"
                  name="search"
                  autoComplete="off"
                  value={search}
                  disabled={controlsLocked}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Name or #TAG…"
                />
              </label>
            </div>
            <ListToolbar
              className="participation-list-toolbar"
              scope={
                <CwlPoolTabs
                  compactLabels
                  id="participation-pools"
                  value={pool}
                  disabled={controlsLocked}
                  onChange={(next) => {
                    choosePool(next);
                    setClan("all");
                    emit({ pool: next, clan: "all" }, false);
                  }}
                />
              }
              filters={
                <FiltersTrigger
                  className="participation-filters-trigger"
                  count={Number(activeOutcome !== "all")}
                  open={listPanel === "filters"}
                  disabled={controlsLocked || !ruleShown}
                  onClick={(event) => {
                    setListTrigger(event.currentTarget);
                    setListPanel("filters");
                  }}
                />
              }
              sort={
                <SortTrigger
                  label={
                    sort === "attacks-desc"
                      ? "Attacks high to low"
                      : sort === "stars-desc"
                        ? "Stars high to low"
                        : "Name A–Z"
                  }
                  disabled={controlsLocked}
                  aria-expanded={listPanel === "sort"}
                  onClick={(event) => {
                    setListTrigger(event.currentTarget);
                    setListPanel("sort");
                  }}
                />
              }
            />
            {listPanel === "filters" && ruleShown && (
              <ActionPanel
                title="Filter results"
                trigger={listTrigger}
                onClose={() => setListPanel(null)}
              >
                <FilterChips
                  label="Outcome"
                  className="participation-outcomes filter-chips--flow"
                  variant="pill"
                  value={activeOutcome}
                  disabled={controlsLocked}
                  options={(["all", ...outcomeOrder] as const)
                    .filter(
                      (value) =>
                        !["did_not_join", "filler", "not_assigned"].includes(
                          value,
                        ) ||
                        counts[value] > 0 ||
                        activeOutcome === value,
                    )
                    .map((value) => ({
                      value,
                      label: value === "all" ? "All" : outcomeLabels[value],
                      count: counts[value],
                    }))}
                  onChange={(next) => {
                    setOutcome(next);
                    emit({ outcome: next });
                  }}
                />
              </ActionPanel>
            )}
            {listPanel === "sort" && (
              <ActionPanel
                title="Sort results"
                trigger={listTrigger}
                onClose={() => setListPanel(null)}
              >
                <div className="participation-sort-options">
                  {(
                    [
                      ["name", "Name A–Z"],
                      ["attacks-desc", "Attacks high to low"],
                      ["stars-desc", "Stars high to low"],
                    ] as const
                  ).map(([value, label]) => (
                    <Button
                      key={value}
                      disabled={controlsLocked}
                      aria-pressed={sort === value}
                      onClick={() => {
                        setSort(value);
                        emit({ sort: value });
                        setListPanel(null);
                      }}
                    >
                      {label}
                    </Button>
                  ))}
                </div>
              </ActionPanel>
            )}
            <div className="participation-list-heading">
              <strong>Players</strong>
              <span>
                {visible.length === poolAccounts.length
                  ? countText(poolAccounts.length, "player")
                  : `${visible.length} of ${countText(poolAccounts.length, "player")}`}{" "}
                · {poolLabel}
                {activeOutcome !== "all"
                  ? ` · ${outcomeLabels[activeOutcome]}`
                  : ""}
              </span>
            </div>
            {data.accounts.length ? (
              <>
                <ul className="participation-list">
                  {sorted
                    .filter(
                      (account) =>
                        visibleTags.has(account.tag) ||
                        dirtyTags.has(account.tag) ||
                        activeEditorTag === account.tag,
                    )
                    .map((account) => (
                      <li
                        key={`${seasonId}:${recordEpoch}:${account.tag}`}
                        hidden={!visibleTags.has(account.tag)}
                      >
                        <ParticipationRecord
                          account={account}
                          mainMinimum={mainMinimum}
                          publicationVersion={data.publication_version}
                          readonly={!!archived}
                          locked={
                            activeEditorTag === account.tag
                              ? ownRecordLocked
                              : writesLocked
                          }
                          open={activeEditorTag === account.tag}
                          onOpen={() => setActiveEditorTag(account.tag)}
                          onClose={() =>
                            setActiveEditorTag((current) =>
                              current === account.tag ? null : current,
                            )
                          }
                          onSave={save}
                          onReset={resetToSource}
                          onDirty={onDirty}
                          onAddStrike={onAddStrike}
                          infractions={onBonus ? infractions : undefined}
                        />
                      </li>
                    ))}
                </ul>
                {!visible.length && (
                  <EmptyState
                    title="No matching players"
                    line="Select another pool or change the filters."
                  />
                )}
              </>
            ) : (
              <EmptyState
                title="No signup accounts yet"
                line="Current signups will appear here."
              />
            )}
            {visible.length > 0 && (
              <div className="roster-load-more" aria-live="polite">
                <span>
                  Showing {shown.length} of {visible.length} matching players
                </span>
                {shown.length < visible.length && (
                  <Button
                    disabled={controlsLocked}
                    onClick={() =>
                      setRenderLimit({
                        key: filterKey,
                        count: shown.length + 50,
                      })
                    }
                  >
                    Load more
                  </Button>
                )}
              </div>
            )}
          </SectionTabPanel>
        </>
      )}
      {settingsOpen && seasonId && (
        <ResultsSettingsSheet
          seasonId={seasonId}
          canCapture
          canOdds={!!onBonus}
          archived={!!archived}
          dirtyResults={dirtyTags.size}
          trigger={settingsTrigger.current}
          onDirty={setSettingsDirty}
          onClose={() => setSettingsOpen(false)}
          onSaved={settingsSaved}
        />
      )}
    </div>
  );
}
