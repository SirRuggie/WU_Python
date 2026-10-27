import ConfirmDialog from "./ConfirmDialog";
import RosterBalance from "./RosterBalance";
import type { MemberOption } from "./MemberPicker";
import RosterDiscordIdentity from "./RosterDiscordIdentity";
import { rosterAccountPages, rosterMemberKey } from "./rosterGrouping";
import DashboardIcon from "./DashboardIcon";
import SignupActivity from "./SignupActivity";
import useWorkspacePreference from "./useWorkspacePreference";
import useUnsavedWork from "./useUnsavedWork";
import { rosterDestinationMenuOptions } from "./ClanDestinationOptions";
import RosterMenu from "./rosterUi/Menu";
import { Button, Input } from "./rosterUi/primitives";
import { Check, RefreshCw } from "lucide-react";
import "./rosterUi/rosterRefresh.css";
import CwlPoolTabs, { useCwlPool } from "./CwlPoolTabs";
import RosterPlayerDialog from "./RosterPlayerDialog";
import RosterSignupPanel from "./RosterSignupPanel";
import RosterAssignPanel from "./RosterAssignPanel";
import RosterSelectionBar from "./RosterSelectionBar";
import RosterUndoToast from "./RosterUndoToast";
import type { RosterUndoState } from "./rosterUndoModel";
import {
  reconcileRosterSelection,
  rosterSelectionSummary,
} from "./rosterReleaseModel";
import StaffSignupControls from "./StaffSignupControls";
import { useDashboardPermission } from "./DashboardPermissions";
import TownHallIcon from "./TownHallIcon";
import "./RosterWorkspace.css";
import { compactRosterWeight } from "./rosterCompactWeight";
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
  mergeRosterMetadata,
  filterRosterAccounts,
  sortRosterAccounts,
  parseWeightK,
  weightInputText,
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
  const [panel, setPanel] = useState<
    "assign" | "signup" | "balance" | "auto" | null
  >(null);
  const [panelTrigger, setPanelTrigger] = useState<HTMLElement | null>(null);
  const [barHeight, setBarHeight] = useState(0);
  const [undoToast, setUndoToast] = useState<RosterUndoState | null>(null);
  const undoReceipt = useRef<{
    id: number;
    revision: number;
    label: string;
  } | null>(null);
  const mutationPending = useRef(false);
  const openPanel = (
    next: "assign" | "signup" | "balance" | "auto",
    trigger: HTMLElement,
  ) => {
    setPanelTrigger(trigger);
    setFeedback(null);
    setPanel(next);
  };
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
  const [groupMembers, setGroupMembers] = useState<
    Record<string, MemberOption>
  >({});
  const [groupNamesLoading, setGroupNamesLoading] = useState(false);
  const [groupNamesError, setGroupNamesError] = useState(false);
  const [groupNamesRetry, setGroupNamesRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setGroupMembers({});
    setGroupNamesError(false);
    setGroupNamesLoading(groupByDiscord);
    if (!groupByDiscord) return;
    api<{ options: MemberOption[] }>(
      `/staff-signup-members?season_id=${encoded(seasonId)}`,
    )
      .then((data) => {
        if (active)
          setGroupMembers(
            Object.fromEntries(
              data.options.map((member) => [member.id, member]),
            ),
          );
      })
      .catch(() => {
        if (active) setGroupNamesError(true);
      })
      .finally(() => {
        if (active) setGroupNamesLoading(false);
      });
    return () => {
      active = false;
    };
  }, [groupByDiscord, seasonId, groupNamesRetry]);
  const [bulkReview, setBulkReview] = useState<{
    text: string;
    clearClan: boolean;
  } | null>(null);
  const balanceOpen = panel === "balance" || panel === "auto";
  const [minWeight, setMinWeight] = useState("");
  const [maxWeight, setMaxWeight] = useState("");
  const [hostFilter, setHostFilter] = useState("");
  const [includeLockedBulk, setIncludeLockedBulk] = useState(false);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [rulesDirty, setRulesDirty] = useState(false);
  const [weightsDirty, setWeightsDirty] = useState(false);
  const [playerDirty, setPlayerDirty] = useState(false);
  const [signupDirty, setSignupDirty] = useState(false);
  const [signupBusy, setSignupBusy] = useState(false);
  const [signupReviewOpen, setSignupReviewOpen] = useState(false);
  const [signupOpen, setSignupOpen] = useState(false);
  const working = busy || signupBusy;
  const uiLocked =
    working || signupReviewOpen || signupOpen || !!panel || !!bulkReview;
  const dirty =
    !!bulkReview ||
    !!panel ||
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
  const focusListHeading = () =>
    requestAnimationFrame(() =>
      requestAnimationFrame(() =>
        listHeading.current?.focus({ preventScroll: true }),
      ),
    );
  const requestId = useRef(0);
  const [metadataRequest, setMetadataRequest] = useState(0);
  const [metadataNotice, setMetadataNotice] = useState("");
  const activeSeason = useRef(seasonId);
  activeSeason.current = seasonId;

  const refresh = useCallback(async () => {
    if (!seasonId) return null;
    const id = ++requestId.current;
    try {
      const snapshot = await api<RosterSnapshot>(
        `/seasons/${encoded(seasonId)}/roster?background=1`,
      );
      if (id !== requestId.current || activeSeason.current !== seasonId)
        return null;
      setRoster(snapshot);
      setMetadataNotice("");
      setMetadataRequest(id);
      return snapshot;
    } catch (error) {
      if (id === requestId.current && activeSeason.current === seasonId) {
        setRoster((current) =>
          current ? { ...current, metadata_updating: false } : current,
        );
      }
      if (
        id === requestId.current &&
        activeSeason.current === seasonId &&
        error instanceof ApiError &&
        [401, 403].includes(error.status)
      ) {
        setRoster(null);
        setSelectedTags([]);
        setEditingTag(null);
        setManualTag(null);
        setPanel(null);
      }
      throw error;
    }
  }, [seasonId]);
  useEffect(() => {
    setEditingTag(null);
    setManualTag(null);
    setRoster(null);
    setPanel(null);
    setUndoToast(null);
    undoReceipt.current = null;
    setFeedback(null);
    setSelectedTags([]);
    setBulkReview(null);
    setPanel(null);
    setIncludeLockedBulk(false);
    setMinWeight("");
    setMaxWeight("");
    setHostFilter("");
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

  useEffect(() => {
    if (!metadataRequest || !roster?.metadata_updating) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const deadline = Date.now() + 90_000;
    const revision = roster.revision;
    const poll = async () => {
      if (!alive || metadataRequest !== requestId.current) return;
      if (Date.now() >= deadline) {
        setRoster((current) =>
          current ? { ...current, metadata_updating: false } : current,
        );
        setMetadataNotice(
          "Some live clan details are still unavailable. Refresh roster to check again.",
        );
        return;
      }
      if (document.hidden) {
        timer = setTimeout(poll, 2000);
        return;
      }
      try {
        const snapshot = await api<RosterSnapshot>(
          `/seasons/${encoded(seasonId)}/roster?background=1`,
        );
        if (
          !alive ||
          metadataRequest !== requestId.current ||
          activeSeason.current !== seasonId
        )
          return;
        if (snapshot.revision !== revision) {
          setRoster((current) =>
            current ? { ...current, metadata_updating: false } : current,
          );
          setMetadataNotice(
            "The roster changed. Refresh roster to see the latest assignments.",
          );
          return;
        }
        setRoster((current) =>
          current ? mergeRosterMetadata(current, snapshot) : current,
        );
        if (snapshot.metadata_updating) timer = setTimeout(poll, 2000);
      } catch (error) {
        if (!alive || metadataRequest !== requestId.current) return;
        if (error instanceof ApiError && [401, 403].includes(error.status)) {
          setRoster(null);
          setSelectedTags([]);
          setEditingTag(null);
          setManualTag(null);
          setPanel(null);
          setFeedback({ kind: "error", text: errorText(error) });
        } else {
          setRoster((current) =>
            current ? { ...current, metadata_updating: false } : current,
          );
          setMetadataNotice(
            "Live clan details could not refresh. Saved assignments are still shown.",
          );
        }
      }
    };
    timer = setTimeout(poll, 1500);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // A fresh saved snapshot starts one bounded, non-overlapping enrichment pass.
    // Metadata updates themselves must not restart its deadline.
  }, [metadataRequest, seasonId]);

  const previousPermissions = useRef({ canRoster, canSignups });
  useEffect(() => {
    const previous = previousPermissions.current;
    if (
      (previous.canRoster && !canRoster) ||
      (previous.canSignups && !canSignups)
    ) {
      setSelectedTags([]);
      setPanel(null);
    }
    previousPermissions.current = { canRoster, canSignups };
    if (!canRoster && !canSignups) {
      setSelectedTags([]);
      setPanel(null);
    } else if (roster)
      setSelectedTags((current) =>
        reconcileRosterSelection(current, roster.accounts),
      );
    if (
      roster &&
      undoReceipt.current &&
      roster.revision !== undoReceipt.current.revision
    ) {
      setUndoToast({
        status: "unavailable",
        message: "Undo no longer available",
      });
    }
  }, [roster, canRoster, canSignups]);

  const afterWrite = async (success: string) => {
    try {
      const latest = await refresh();
      if (latest?.undo && latest.undo.revision === latest.revision) {
        undoReceipt.current = latest.undo;
        setUndoToast({ status: "available", label: latest.undo.label });
      }
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
      setPanel(null);
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
      setPanel(null);
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
    if (!canSignups || !roster || !seasonId || working || archived)
      return false;
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
            (!hostFilter || account.assigned_clan_tag === hostFilter) &&
            (!minWeight ||
              (account.effective_weight !== null &&
                account.effective_weight >= Number(minWeight) * 1000)) &&
            (!maxWeight ||
              (account.effective_weight !== null &&
                account.effective_weight <= Number(maxWeight) * 1000)) &&
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
      setManualTag(null);
      previousFilter.current = filterKey;
    }
  }, [filterKey]);
  const visibleTags = pageAccounts.map((account) => account.tag);
  const selectionSummary = rosterSelectionSummary(
    selectedTags,
    roster?.accounts || [],
    filtered,
    pageAccounts,
  );
  const hiddenTags = selectedTags.filter(
    (tag) => !filtered.some((account) => account.tag === tag),
  );
  const hiddenSelection = selectionSummary.outsideFilterSelectedCount;
  const allVisibleSelected =
    visibleTags.length > 0 &&
    visibleTags.every((tag) => selectedTags.includes(tag));
  const toggleSelected = (tag: string) =>
    setSelectedTags((current) =>
      current.includes(tag)
        ? current.filter((item) => item !== tag)
        : [...current, tag],
    );
  const bulkAssign = async (clearClan = false, confirmed = false) => {
    if (!canRoster || !roster || !seasonId || working || archived) return;
    const sourceTags = clearClan
      ? roster.accounts
          .filter((a) => a.assigned_clan_tag === hostFilter)
          .map((a) => a.tag)
      : selectedTags;
    const actionTags = sourceTags.filter(
      (tag) =>
        includeLockedBulk || !roster.accounts.find((a) => a.tag === tag)?.kept,
    );
    const destination = "__unassign__";
    if (!actionTags.length) {
      setFeedback({
        kind: "error",
        text: "No unlocked accounts selected. Enable Include locked placements to move locked accounts.",
      });
      return;
    }
    if (actionTags.length > 50) {
      setFeedback({
        kind: "error",
        text: "Select up to 50 accounts per bulk assignment.",
      });
      return;
    }
    const actionSummary =
      destination === "__unassign__"
        ? `Unassign ${actionTags.length} account${actionTags.length === 1 ? "" : "s"}${clearClan ? ` from ${clanName(hostFilter)}` : " from the working roster"}?`
        : `Assign ${actionTags.length} selected account${actionTags.length === 1 ? "" : "s"} to ${clanName(destination)}?`;
    if (!confirmed) {
      setBulkReview({
        text: `${actionSummary} Signups stay unchanged. ${sourceTags.length - actionTags.length} locked placement(s) excluded. Publish separately when ready.`,
        clearClan,
      });
      return;
    }
    setBulkReview(null);
    const sid = seasonId;
    setBusy(true);
    setFeedback(null);
    try {
      const result = await api<{ revision: number; updated: number }>(
        `/seasons/${encoded(sid)}/roster/assignments`,
        "PATCH",
        {
          revision: roster.revision,
          tags: actionTags,
          include_locked: includeLockedBulk,
          assigned_clan_tag:
            destination === "__unassign__" ? null : destination,
        },
      );
      if (activeSeason.current === sid) {
        setSelectedTags([]);
        await afterWrite(
          `${result.updated} account${result.updated === 1 ? "" : "s"} ${destination === "__unassign__" ? "unassigned" : "assigned to " + clanName(destination)}.`,
        );
      }
    } catch (error) {
      if (activeSeason.current === sid) await fail(error);
    } finally {
      setBusy(false);
    }
  };
  const assignSelected = async (
    destination: string | null,
  ): Promise<boolean> => {
    if (
      !canRoster ||
      !roster ||
      !seasonId ||
      working ||
      archived ||
      mutationPending.current ||
      !selectedTags.length ||
      selectedTags.length > 50
    )
      return false;
    const sid = seasonId;
    mutationPending.current = true;
    setBusy(true);
    setFeedback(null);
    try {
      await api(`/seasons/${encoded(sid)}/roster/assignments`, "PATCH", {
        revision: roster.revision,
        tags: selectedTags,
        assigned_clan_tag: destination,
        include_locked: true,
      });
      if (activeSeason.current === sid)
        await afterWrite(
          destination
            ? "Accounts assigned. Placements locked."
            : "Accounts unassigned. Signups kept.",
        );
      return true;
    } catch (cause) {
      if (activeSeason.current === sid) await fail(cause);
      return false;
    } finally {
      mutationPending.current = false;
      setBusy(false);
    }
  };
  const bulkChangeSignups = async (
    action: Pool | "remove",
    tags: string[],
  ): Promise<boolean> => {
    if (
      !canSignups ||
      !roster ||
      !seasonId ||
      working ||
      archived ||
      !tags.length ||
      tags.length > 50
    )
      return false;
    const available = new Set(roster.accounts.map((account) => account.tag));
    if (tags.some((tag) => !available.has(tag))) {
      setFeedback({
        kind: "error",
        text: "The selection changed. Clear it and choose the accounts again.",
      });
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
        await afterWrite(
          `${result.count} signup${result.count === 1 ? "" : "s"} ${action === "remove" ? "removed" : `changed to ${action === "main" ? "Main" : "Lazy"} CWL`}. Publish again to update the published roster.`,
        );
        if (fromBulk) focusListHeading();
      }
      return true;
    } catch (error) {
      if (activeSeason.current === sid) {
        if (error instanceof ApiError && error.status === 409) {
          const fromBulk = selectedTags.length > 0;
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
    if (
      !canRoster ||
      !roster ||
      !undoReceipt.current ||
      !seasonId ||
      uiLocked ||
      archived ||
      mutationPending.current
    )
      return;
    const sid = seasonId;
    mutationPending.current = true;
    setUndoToast({ status: "pending", label: undoReceipt.current.label });
    setBusy(true);
    setFeedback(null);
    try {
      await api(`/seasons/${encoded(sid)}/roster/undo`, "POST", {
        revision: roster.revision,
        undo_id: undoReceipt.current.id,
      });
      if (activeSeason.current === sid) {
        undoReceipt.current = null;
        setUndoToast(null);
        await afterWrite("Last placement change undone.");
      }
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
        setUndoToast({
          status: "unavailable",
          message:
            error instanceof ApiError && [404, 409].includes(error.status)
              ? "Undo no longer available"
              : "Undo could not be confirmed. Refresh the roster before trying again.",
        });
      }
    } finally {
      mutationPending.current = false;
      setBusy(false);
    }
  };
  const poolAccounts =
    roster?.accounts.filter(
      (account) => viewPool === "all" || account.pool === viewPool,
    ) || [];
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
    <div
      className={`roster-workspace roster-ui${mode === "assign" ? " roster-workspace-assign" : ""}`}
      style={{
        paddingBottom: selectedTags.length ? barHeight + 24 : undefined,
      }}
    >
      {bulkReview && (
        <ConfirmDialog
          heading="Update working assignments?"
          text={bulkReview.text}
          confirmLabel="Update assignments"
          onCancel={() => setBulkReview(null)}
          onConfirm={() => void bulkAssign(bulkReview.clearClan, true)}
        />
      )}
      {roster && panel === "assign" && (
        <RosterAssignPanel
          roster={roster}
          selectedAccounts={selectedAccounts}
          hiddenTags={hiddenTags}
          busy={working}
          trigger={panelTrigger}
          onClose={() => setPanel(null)}
          onAssign={assignSelected}
        />
      )}
      {roster && panel === "signup" && (
        <RosterSignupPanel
          accounts={selectedAccounts}
          clans={roster.clans}
          hiddenTags={hiddenTags}
          busy={working}
          error={feedback?.kind === "error" ? feedback.text : undefined}
          trigger={panelTrigger}
          onClose={() => setPanel(null)}
          onApply={bulkChangeSignups}
          onReviewChange={setSignupReviewOpen}
        />
      )}
      {balanceOpen && roster && (
        <RosterBalance
          roster={roster}
          seasonId={seasonId}
          tags={selectedTags}
          hiddenTags={hiddenTags}
          trigger={panelTrigger}
          automatic={panel === "auto"}
          pool={viewPool}
          onClose={() => setPanel(null)}
          onBusy={setBusy}
          onPermissionError={(error) => void fail(error)}
          onSaved={async () => {
            await afterWrite(
              "Placements applied. Signups unchanged. Publish when ready.",
            );
          }}
        />
      )}
      {undoToast && !panel && canRoster && (
        <RosterUndoToast
          state={undoToast}
          bottomOffset={selectedTags.length ? barHeight + 24 : 16}
          onDismiss={() => setUndoToast(null)}
          onUndo={() => void undoPlacement()}
        />
      )}
      {mode === "assign" && !archived && (
        <RosterSelectionBar
          selectedCount={selectedTags.length}
          hiddenCount={hiddenSelection}
          busy={working}
          canRoster={canRoster}
          canSignups={canSignups}
          hidden={!!panel || !!editingTag || !!bulkReview}
          onAssign={(trigger) => openPanel("assign", trigger)}
          onBalance={(trigger) => openPanel("balance", trigger)}
          onSignup={(trigger) => openPanel("signup", trigger)}
          onClear={() => setSelectedTags([])}
          onHeight={setBarHeight}
        />
      )}
      <div className="page-head">
        <div>
          <p className="eyebrow">Staff roster</p>
          <h1>CWL roster &amp; signups</h1>
          <p>Working placements stay private until published.</p>
        </div>
        <RosterMenu
          label="Season"
          value={seasonId}
          disabled={uiLocked}
          onValueChange={(value) => {
            if (mayLeaveEditor()) onSeasonChange(value);
          }}
          options={[
            { value: "", label: "Select a season" },
            ...seasons.map((season) => ({
              value: String(season.id),
              label: season.label,
            })),
          ]}
        />
      </div>
      {seasonId && canSignups && (
        <SignupActivity key={seasonId} seasonId={seasonId} />
      )}
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
            <Button
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
            </Button>
          )}
          <Button
            aria-label="Dismiss message"
            onClick={() => setFeedback(null)}
          >
            ×
          </Button>
        </div>
      )}
      {loading && <p role="status">Loading roster…</p>}
      {roster?.metadata_updating && (
        <p className="muted" role="status">
          Updating live clan details… Saved assignments are ready.
        </p>
      )}
      {metadataNotice && <p role="status">{metadataNotice}</p>}
      {roster && (
        <>
          {canRoster && (
            <div
              className="roster-workflow-nav"
              role="group"
              aria-label="Roster workspace views"
            >
              {(
                [
                  { id: "assign", label: "Accounts & signups" },
                  { id: "compare", label: "Compare clans" },
                  { id: "rules", label: "Clan settings" },
                  {
                    id: "weights",
                    label: `Weights · ${missingWeight} missing`,
                  },
                ] as const
              ).map((item) => (
                <Button
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
                </Button>
              ))}
            </div>
          )}
          {mode === "assign" ? (
            <div
              className="roster-list-pool-tabs workflow-tabs"
              role="group"
              aria-label="Show CWL accounts"
            >
              {(["all", "main", "lazy"] as const).map((pool) => (
                <Button
                  type="button"
                  key={pool}
                  aria-pressed={listPool === pool}
                  disabled={uiLocked}
                  onClick={() => {
                    if (
                      working ||
                      ((playerDirty || !!manualTag) && !mayLeaveEditor())
                    )
                      return;
                    setListPool(pool);
                    if (pool !== "all") setPoolFilter(pool);
                    setPanel(null);
                    setSearch("");
                    setEditingTag(null);
                  }}
                >
                  {pool === "all"
                    ? "All accounts"
                    : pool === "main"
                      ? "Main CWL"
                      : "Lazy CWL"}
                </Button>
              ))}
            </div>
          ) : (
            <CwlPoolTabs
              value={poolFilter}
              disabled={uiLocked}
              onChange={(pool) => {
                if (!mayLeaveEditor()) return;
                setPoolFilter(pool);
                setPanel(null);
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
              disabled={
                busy ||
                selectedTags.length > 0 ||
                !!manualTag ||
                !!editingTag ||
                rulesDirty ||
                weightsDirty
              }
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
          {mode === "assign" && (
            <div className="roster-assign-summary" role="status">
              <span>
                <strong>{poolAccounts.length}</strong> signed up
              </span>
              <span>
                <strong>{assigned}</strong> assigned
              </span>
              <span>
                <strong>{poolAccounts.length - assigned}</strong> awaiting
                placement
              </span>
              <span>
                <strong>{missingWeight}</strong> missing weight
              </span>
            </div>
          )}
          <div className="roster-toolbar">
            <Button
              icon={RefreshCw}
              disabled={uiLocked}
              onClick={() => {
                if (mayLeaveEditor())
                  void refresh().catch((error) =>
                    setFeedback({ kind: "error", text: errorText(error) }),
                  );
              }}
            >
              Refresh roster
            </Button>
            {canRoster && mode === "assign" && (
              <Button
                disabled={
                  uiLocked ||
                  archived ||
                  !roster.clans.some((clan) => !clan.archived)
                }
                onClick={(event) => openPanel("auto", event.currentTarget)}
              >
                Auto-place unassigned…
              </Button>
            )}
            {canRoster && onReviewPublication && mode !== "assign" && (
              <Button
                variant="primary"
                disabled={busy}
                onClick={onReviewPublication}
              >
                Finalize both groups →
              </Button>
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
                  <RosterMenu
                    label="Hosting clan"
                    value={ruleClan.tag}
                    disabled={busy}
                    onValueChange={(value) => {
                      if (mayLeaveEditor()) setRuleTag(value);
                    }}
                    options={activeClans.map((clan) => ({
                      value: clan.tag,
                      label: `${clan.name} · ${clan.cwl_league || "League unavailable"} · ${clan.tag}`,
                    }))}
                  />
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
              rosterUi
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
          {mode === "assign" && (
            <>
              <div className="roster-account-tools">
                <div className="roster-quick-search">
                  <label>
                    Find accounts
                    <Input
                      value={search}
                      disabled={uiLocked}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Name, tag or Discord ID"
                    />
                  </label>
                  <RosterMenu
                    label="Show"
                    value={assignmentFilter}
                    disabled={uiLocked}
                    onValueChange={(value) =>
                      setAssignmentFilter(
                        value as "all" | "assigned" | "unassigned",
                      )
                    }
                    options={[
                      { value: "all", label: "All accounts" },
                      { value: "unassigned", label: "Unassigned" },
                      { value: "assigned", label: "Assigned" },
                    ]}
                  />
                  <RosterMenu
                    label="Sort"
                    value={sort}
                    disabled={uiLocked}
                    onValueChange={(value) => setSort(value as RosterSort)}
                    options={[
                      { value: "name", label: "Name A–Z" },
                      { value: "town_hall_desc", label: "TH: highest first" },
                      { value: "town_hall_asc", label: "TH: lowest first" },
                      { value: "weight_desc", label: "Weight: highest first" },
                      { value: "weight_asc", label: "Weight: lowest first" },
                    ]}
                  />
                </div>
                <details className="roster-more-filters">
                  <summary>
                    Filters · Weight, league &amp; grouping{" "}
                    {readinessFilter !== "all" ||
                    leagues.length ||
                    townHalls.length ||
                    groupByDiscord ||
                    minWeight ||
                    maxWeight ||
                    hostFilter
                      ? "· Active"
                      : ""}
                  </summary>
                  <div className="roster-weight-range">
                    <label>
                      Minimum weight (k)
                      <Input
                        type="number"
                        min="0"
                        step="any"
                        placeholder="174"
                        value={minWeight}
                        disabled={uiLocked}
                        onChange={(e) => {
                          setMinWeight(e.target.value);
                          setPage(0);
                        }}
                      />
                    </label>
                    <label>
                      Maximum weight (k)
                      <Input
                        type="number"
                        min="0"
                        step="any"
                        placeholder="Any"
                        value={maxWeight}
                        disabled={uiLocked}
                        onChange={(e) => {
                          setMaxWeight(e.target.value);
                          setPage(0);
                        }}
                      />
                    </label>
                  </div>
                  {minWeight &&
                    maxWeight &&
                    Number(minWeight) > Number(maxWeight) && (
                      <p role="alert">
                        Maximum weight must be at least the minimum.
                      </p>
                    )}
                  <RosterMenu
                    label="Assigned clan"
                    value={hostFilter}
                    disabled={uiLocked}
                    onValueChange={(value) => {
                      setHostFilter(value);
                      setPage(0);
                    }}
                    options={[
                      { value: "", label: "All hosting clans" },
                      ...roster.clans.map((clan) => ({
                        value: clan.tag,
                        label: clan.name,
                      })),
                    ]}
                  />
                  {hostFilter && canRoster && (
                    <details>
                      <summary>Clan actions</summary>
                      <label className="roster-group-toggle">
                        <input
                          type="checkbox"
                          checked={includeLockedBulk}
                          disabled={uiLocked}
                          onChange={(e) =>
                            setIncludeLockedBulk(e.target.checked)
                          }
                        />
                        Include locked placements
                      </label>
                      <Button
                        disabled={uiLocked || archived}
                        onClick={() => void bulkAssign(true)}
                      >
                        Clear clan assignments
                      </Button>
                      <small>
                        Clears this clan’s assignments across all filters. Keeps
                        signups.
                      </small>
                    </details>
                  )}
                  <label className="roster-group-toggle">
                    <input
                      type="checkbox"
                      checked={groupByDiscord}
                      disabled={uiLocked || !!manualTag || !!editingTag}
                      onChange={(event) => {
                        setGroupByDiscord(event.target.checked);
                        setPage(0);
                      }}
                    />
                    Group by Discord user
                  </label>
                  <div className="card readiness-filter">
                    <RosterMenu
                      label="Readiness check"
                      value={readinessFilter}
                      disabled={uiLocked}
                      onValueChange={(value) =>
                        setReadinessFilter(value as ReadinessFilter)
                      }
                      options={[
                        { value: "all", label: "All accounts" },
                        { value: "unassigned", label: "Unassigned accounts" },
                        { value: "missing_weight", label: "Missing weights" },
                        {
                          value: "over_capacity",
                          label: "Clans over capacity",
                        },
                      ]}
                    />
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
                      }}
                    />
                    <Button
                      disabled={uiLocked}
                      onClick={() => {
                        setMinWeight("");
                        setMaxWeight("");
                        setHostFilter("");
                        setGroupByDiscord(false);
                        setLeagues([]);
                        setTownHalls([]);
                        setSearch("");
                        setAssignmentFilter("all");
                        setReadinessFilter("all");
                      }}
                    >
                      Clear filters
                    </Button>
                    <small>
                      {filtered.length} of {poolAccounts.length} accounts shown.
                      League filters use the assigned clan; unassigned accounts
                      have no league.
                    </small>
                  </div>
                </details>
              </div>
              {!selectedTags.length && canRoster && (
                <p className="roster-selection-hint">
                  To balance clans, select accounts below, then choose{" "}
                  <strong>Balance across clans</strong>.
                </p>
              )}
              <div
                className="roster-list-heading"
                ref={listHeading}
                tabIndex={-1}
              >
                <label className="roster-select-all">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    disabled={
                      uiLocked ||
                      archived ||
                      (!canRoster && !canSignups) ||
                      !visibleTags.length
                    }
                    onChange={(event) =>
                      setSelectedTags(
                        event.target.checked
                          ? [...new Set([...selectedTags, ...visibleTags])]
                          : selectedTags.filter(
                              (tag) => !visibleTags.includes(tag),
                            ),
                      )
                    }
                  />{" "}
                  Select all {visibleTags.length} on this page
                </label>
                <span>
                  {`${filtered.length} matching · ${selectedTags.length} selected`}
                </span>
              </div>
              {filtered.length > visibleTags.length &&
                filtered.length <= 50 && (
                  <Button
                    disabled={
                      uiLocked || archived || (!canRoster && !canSignups)
                    }
                    onClick={() => setSelectedTags(filtered.map((a) => a.tag))}
                  >
                    Select all {filtered.length} matching accounts
                  </Button>
                )}
              {groupByDiscord && groupNamesError && (
                <p role="status">
                  Discord profiles could not be loaded. Accounts remain grouped
                  by Discord ID.
                  <Button
                    type="button"
                    onClick={() => setGroupNamesRetry((value) => value + 1)}
                  >
                    Retry profiles
                  </Button>
                </p>
              )}
              {filtered.length ? (
                <div className="roster-account-list">
                  {pageAccounts.map((account, index) => (
                    <Fragment key={account.tag}>
                      {groupByDiscord &&
                        (index === 0 ||
                          rosterMemberKey(pageAccounts[index - 1]) !==
                            rosterMemberKey(account)) && (
                          <header className="roster-member-heading">
                            <RosterDiscordIdentity
                              userId={account.user_id}
                              resolvedMember={
                                groupMembers[account.user_id] || null
                              }
                              resolving={groupNamesLoading}
                            />
                            <small>
                              {
                                pageAccounts.filter(
                                  (item) =>
                                    rosterMemberKey(item) ===
                                    rosterMemberKey(account),
                                ).length
                              }{" "}
                              accounts shown
                            </small>
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
                                uiLocked ||
                                archived ||
                                (!canRoster && !canSignups)
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
                              {account.tag} · TH {account.town_hall ?? "—"}
                              {viewPool === "all"
                                ? ` · ${account.pool === "main" ? "Main" : "Lazy"} CWL`
                                : ""}
                            </small>
                          </div>
                        </div>
                        <div className="roster-row-summary">
                          <span
                            className="roster-row-weight"
                            aria-label={`Weight: ${account.effective_weight == null ? "Missing weight" : compactRosterWeight(account.effective_weight)}`}
                          >
                            <small>Weight</small>
                            <strong>
                              {account.effective_weight == null
                                ? "Missing weight"
                                : compactRosterWeight(account.effective_weight)}
                            </strong>
                          </span>
                          <div className="roster-row-clans">
                            <span className="roster-row-host">
                              <small>Hosting clan</small>
                              <strong>
                                {account.kept && (
                                  <span
                                    className="roster-placement-lock"
                                    role="img"
                                    aria-label="Locked placement: auto-place will not move this account"
                                    title="Locked placement: auto-place will not move this account"
                                  >
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
                                {account.current_clan_status ===
                                  "unavailable" || !account.current_clan_status
                                  ? "Unavailable"
                                  : account.current_clan_name ||
                                    account.current_clan_tag ||
                                    "No clan"}
                              </strong>
                              {account.outside_family_and_hosts && (
                                <small className="roster-outside-label">
                                  Outside family / hosting clans
                                </small>
                              )}
                            </span>
                          </div>
                          {!account.assigned_clan_tag &&
                            (account.kept ||
                              account.auto_placement_reason !== "ready") && (
                              <span className="roster-row-status">
                                {account.kept
                                  ? "Held unassigned · unlock in Details to auto-place"
                                  : account.auto_placement_note ||
                                    "Not assigned"}
                              </span>
                            )}
                        </div>
                        <div className="roster-placement-help">
                          {canRoster && (
                            <Button
                              disabled={uiLocked || archived}
                              onClick={() => {
                                setManualTag(account.tag);
                                setManualClan(account.assigned_clan_tag || "");
                                setFeedback(null);
                              }}
                            >
                              {account.assigned_clan_tag
                                ? "Assign →"
                                : "Assign →"}
                            </Button>
                          )}
                          <Button
                            type="button"
                            disabled={uiLocked}
                            aria-label={`Details for ${account.player_name}`}
                            onClick={() => {
                              setFeedback(null);
                              setEditingTag(account.tag);
                            }}
                          >
                            Details
                          </Button>
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
                            <RosterMenu
                              autoFocus
                              label={`Assign ${account.player_name}`}
                              value={manualClan}
                              disabled={busy}
                              onValueChange={setManualClan}
                              options={[
                                { value: "", label: "Choose a hosting clan" },
                                ...rosterDestinationMenuOptions(
                                  roster.clans,
                                  account.pool,
                                  account.assigned_clan_tag,
                                ),
                              ]}
                            />
                            <p>
                              {account.pool === "lazy"
                                ? "Choose a Lazy host with space."
                                : "Choose an active hosting clan with space."}
                            </p>
                            {feedback?.kind === "error" && (
                              <p role="alert">{feedback.text}</p>
                            )}
                            <Button
                              type="submit"
                              variant="primary"
                              disabled={busy || !manualClan}
                            >
                              {busy ? "Saving…" : "Save placement"}
                            </Button>
                            <Button
                              type="button"
                              disabled={busy}
                              onClick={() => setManualTag(null)}
                            >
                              Cancel
                            </Button>
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
                  <Button
                    disabled={uiLocked || currentPage === 0}
                    onClick={() => {
                      setPage(currentPage - 1);
                      listHeading.current?.scrollIntoView({ block: "start" });
                    }}
                  >
                    ← Previous
                  </Button>
                  <span>
                    Page {currentPage + 1} of {lastPage + 1}
                  </span>
                  <Button
                    disabled={uiLocked || currentPage === lastPage}
                    onClick={() => {
                      setPage(currentPage + 1);
                      listHeading.current?.scrollIntoView({ block: "start" });
                    }}
                  >
                    Next →
                  </Button>
                </nav>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
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
          <RosterMenu
            label="Signup pool"
            value={pool}
            disabled={busy}
            onValueChange={(value) => setPool(value as Pool)}
            options={[
              { value: "", label: "Not set" },
              { value: "main", label: "Main CWL" },
              { value: "lazy", label: "Lazy CWL" },
            ]}
          />
          <RosterMenu
            label="Capacity"
            value={capacity}
            disabled={busy}
            onValueChange={setCapacity}
            options={[
              { value: "", label: "Not set" },
              { value: "15", label: "15" },
              { value: "30", label: "30" },
            ]}
          />
          <label>
            Minimum weight (k, included)
            <Input
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
            <Input
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
        <Button
          type="submit"
          variant="primary"
          icon={Check}
          disabled={busy || stale || !changed}
        >
          Save clan range & rules
        </Button>
        {stale && changed && (
          <p role="alert">
            Clan settings changed elsewhere. Your edits are preserved.
            <Button type="button" disabled={busy} onClick={useLatest}>
              Discard edits and use latest settings
            </Button>
          </p>
        )}
      </fieldset>
    </form>
  );
}
