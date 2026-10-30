import ConfirmDialog from "./ConfirmDialog";
import useStaffDetailsPage from "./useStaffDetailsPage";
import { requestDetailsNavigation } from "./detailsNavigation";
import { sortClans } from "./clanSort";
import { comparisonOrder } from "./compare";
import useLocationNow from "./useLocationNow";
import ClanSettings from "./ClanSettings";
import type { ClanRules } from "./clanSettingsModel";
import { placementMessage } from "./publicationAwareness";
import { createComparisonMemory } from "./comparisonMemory";
import SortTrigger from "./rosterUi/SortTrigger";
import { rosterSortOptions } from "./rosterSortOptions";
import { closeRosterActionMenus } from "./rosterUi/actionMenuState";
import RosterBalance from "./RosterBalance";
import ActionPanel from "./ActionPanel";
import type { MemberOption } from "./MemberPicker";
import RosterDiscordIdentity from "./RosterDiscordIdentity";
import RosterHeader from "./RosterHeader";
import RosterAccountCard from "./RosterAccountCard";
import RosterFilters from "./RosterFilters";
import RosterClanChips from "./RosterClanChips";
import { rosterMemberKey } from "./rosterGrouping";
import useWorkspacePreference from "./useWorkspacePreference";
import useRosterPreferences from "./useRosterPreferences";
import useUnsavedWork from "./useUnsavedWork";
import { Button } from "./rosterUi/primitives";
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
  deriveRosterRelease,
  orderRosterReleaseAccounts,
  progressiveRosterReleaseAccounts,
  toggleAllRosterMatches,
  type RosterReleasePreferences,
} from "./rosterReleaseModel";
import StaffSignupControls from "./StaffSignupControls";
import { useDashboardPermission } from "./DashboardPermissions";
import { useHorizontalFades } from "./useHorizontalFades";
import "./horizontalFades.css";
import "./RosterWorkspace.css";
import WeightQueue from "./WeightQueue";
import CompareClans from "./CompareClans";
import {
  Fragment,
  useCallback,
  useMemo,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { api, ApiError, type Pool, type Season } from "./api";
import {
  assignmentOptions,
  mergeRosterMetadata,
  type RosterClan,
  type RosterSnapshot,
} from "./roster";

type Props = {
  onFamilyClans?: () => void;
  onPublication?: (draft: import("./publication").PublicationDraft) => void;
  onClanWeights?: () => void;
  seasonId: string;
  seasons: Season[];
  onDirty?: (dirty: boolean) => void;
  onDirtySummary?: (summary: { weightCount: number; onlyWeights: boolean }) => void;
  onEditFocus?: (element: HTMLElement) => void;
  onSeasonChange: (id: string) => void;
  initialReadiness?: "all" | "unassigned" | "missing_weight" | "over_capacity";
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
  onClanWeights,
  onFamilyClans,
  onPublication,
  seasons,
  onSeasonChange,
  initialReadiness = "all",
  onReviewPublication,
  onSeasonRefresh,
  onBusy,
  onDirty,
  onDirtySummary,
  onEditFocus,
}: Props) {
  const canRoster = useDashboardPermission("cwl_roster");
  const canSignups = useDashboardPermission("cwl_signups");
  const canSettings = useDashboardPermission("cwl_settings");
  const canPublish = useDashboardPermission("cwl_publish");
  const comparisonMemory = useMemo(createComparisonMemory, [seasonId]);
  const season = seasons.find((item) => String(item.id) === seasonId);
  const archived = season?.status === "archived";
  const [detailsOrder, setDetailsOrder] = useState<string[]>([]);
  const [editingTag, setEditingTag] = useState<string | null>(null);
  const [roster, setRoster] = useState<RosterSnapshot | null>(null);
  const [now] = useLocationNow();
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [hostingBusy, setHostingBusy] = useState(false);
  const [compareJump, setCompareJump] = useState(0);
  const [hasPublication, setHasPublication] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [panel, setPanel] = useState<
    "assign" | "signup" | "balance" | "auto" | null
  >(null);
  const [panelTrigger, setPanelTrigger] = useState<HTMLElement | null>(null);
  const [barHeight, setBarHeight] = useState(0);
  const [filterOpen, setFilterOpen] = useState(false);
  const [sortOpen, setSortOpen] = useState(false);
  const sortTrigger = useRef<HTMLButtonElement>(null);
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
    tags?: string[],
  ) => {
    setPanelTrigger(trigger);
    setPanelTagsOverride(tags ?? null);
    setFeedback(null);
    setPanel(next);
  };
  const closePanel = () => {
    setPanel(null);
    setPanelTagsOverride(null);
  };
  const [mode, setMode] = useWorkspacePreference<
    "assign" | "compare" | "rules" | "weights"
  >(`wu-roster-${seasonId}-mode`, "assign");
  const [renderCount, setRenderCount] = useState(50);
  const [releasePreferences, setReleasePreferences] =
    useRosterPreferences(seasonId);
  const [poolFilter, setPoolFilter] = useCwlPool();
  const [focusClanTag, setFocusClanTag] = useState<string | null>(null);
  const [focusClanRequest, setFocusClanRequest] = useState(0);
  useEffect(() => setFocusClanTag(null), [seasonId]);
  const tabFades = useHorizontalFades<HTMLDivElement>();
  const [refreshEpoch, setRefreshEpoch] = useState(0);
  const viewPool =
    mode === "weights"
      ? "all"
      : mode === "assign"
        ? releasePreferences.pool
        : poolFilter;
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [panelTagsOverride, setPanelTagsOverride] = useState<string[] | null>(
    null,
  );
  const panelTags = panelTagsOverride ?? selectedTags;
  const [groupNamesLoading, setGroupNamesLoading] = useState(false);
  const [groupNamesError, setGroupNamesError] = useState(false);
  const [groupNamesRetry, setGroupNamesRetry] = useState(0);
  const groupByDiscord = releasePreferences.grouped;
  const [groupMembers, setGroupMembers] = useState<
    Record<string, MemberOption>
  >({});
  const appliedInitialReadiness = useRef(false);
  useEffect(() => {
    if (appliedInitialReadiness.current) return;
    appliedInitialReadiness.current = true;
    if (initialReadiness !== "all") {
      setMode(
        initialReadiness === "missing_weight"
          ? "weights"
          : initialReadiness === "over_capacity"
            ? "compare"
            : "assign",
      );
      setReleasePreferences((current) => ({
        ...current,
        statuses: initialReadiness === "unassigned" ? ["unassigned"] : [],
        pool: "all",
      }));
    }
  }, [initialReadiness, setReleasePreferences, setMode]);
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
  const [rulesDirty, setRulesDirty] = useState(false);
  const [weightsDirty, setWeightsDirty] = useState(false);
  const [weightsDirtyCount, setWeightsDirtyCount] = useState(0);
  const lastEditFocus = useRef<HTMLElement | null>(null);
  const [discardToken, setDiscardToken] = useState(0);
  const [playerDirty, setPlayerDirty] = useState(false);
  const [signupDirty, setSignupDirty] = useState(false);
  const [signupBusy, setSignupBusy] = useState(false);
  const [signupReviewOpen, setSignupReviewOpen] = useState(false);
  const [signupOpen, setSignupOpen] = useState(false);
  const working = busy || signupBusy || hostingBusy;
  const uiLocked = working || signupReviewOpen || signupOpen || !!panel;
  const dirty =
    !!panel ||
    rulesDirty ||
    weightsDirty ||
    playerDirty ||
    signupDirty ||
    signupReviewOpen ||
    selectedTags.length > 0;
  const onlyWeightsDirty =
    weightsDirtyCount > 0 &&
    !rulesDirty &&
    !playerDirty &&
    !signupDirty &&
    !signupReviewOpen &&
    !panel &&
    selectedTags.length === 0;
  useUnsavedWork(dirty || working, onDirty);
  useEffect(() => {
    onDirtySummary?.({
      weightCount: weightsDirtyCount,
      onlyWeights: onlyWeightsDirty,
    });
  }, [weightsDirtyCount, onlyWeightsDirty, onDirtySummary]);
  useEffect(() => {
    onBusy?.(working);
    return () => onBusy?.(false);
  }, [working, onBusy]);
  useEffect(() => {
    if (!canRoster && mode !== "assign") setMode("assign");
  }, [canRoster, mode, setMode]);
  const [pendingLeave, setPendingLeave] = useState<null | { action: () => void; working: boolean }>(null);
  const requestLeave = (action: () => void, requiresDiscard = dirty) => {
    if (working) {
      setPendingLeave({ action: () => {}, working: true });
      return false;
    }
    if (requiresDiscard) {
      setPendingLeave({ action, working: false });
      return false;
    }
    action();
    return true;
  };
  const requestSignupNavigation = (action: () => void) => {
    requestDetailsNavigation(() =>
      requestLeave(
        action,
        rulesDirty || weightsDirty || signupDirty || selectedTags.length > 0,
      ),
    );
  };
  const mayLeaveEditor = (action: () => void) => requestLeave(action);
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
      setRefreshEpoch((value) => value + 1);
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
        closePanel();
      }
      throw error;
    }
  }, [seasonId]);
  useLayoutEffect(() => {
    setEditingTag(null);
    setRoster(null);
    closePanel();
    setUndoToast(null);
    undoReceipt.current = null;
    setFeedback(null);
    setSelectedTags([]);
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
          closePanel();
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
      closePanel();
    }
    previousPermissions.current = { canRoster, canSignups };
    if (!canRoster && !canSignups) {
      setSelectedTags([]);
      closePanel();
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

  const afterWrite = async (success: string, placement = false) => {
    if (placement) success = placementMessage(success, hasPublication);
    try {
      const latest = await refresh();
      if (latest?.undo && latest.undo.revision === latest.revision) {
        undoReceipt.current = latest.undo;
        setUndoToast({
          status: "available",
          label: placementMessage(latest.undo.label, hasPublication),
        });
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
      closePanel();
      setFeedback({ kind: "error", text: error.message });
      return;
    }
    if (error instanceof ApiError && error.status === 409) {
      const hadAccountEditor = !!editingTag;
      setEditingTag(null);
      try {
        await refresh();
      } catch {
        /* Original conflict remains the useful error. */
      }
      closePanel();
      setFeedback({
        kind: "error",
        text: hadAccountEditor
          ? `${error.message} The account editor closed. Reopen it to review the latest saved values.`
          : `${error.message} The roster was refreshed; review it and try again.`,
      });
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
      if (activeSeason.current === sid)
        await afterWrite(
          success,
          "assigned_clan_tag" in body || "kept" in body,
        );
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
  const saveRules = async (clan: RosterClan, rules: ClanRules) => {
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
      throw new Error(errorText(error));
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
  const releaseResult = roster
    ? deriveRosterRelease(roster.accounts, roster.clans, {
        ...releasePreferences,
        pool: viewPool,
      })
    : null;
  const filtered = releaseResult
    ? orderRosterReleaseAccounts(
        releaseResult.matches,
        releasePreferences.sort,
        groupByDiscord,
      )
    : [];
  const progressive = progressiveRosterReleaseAccounts(
    filtered,
    renderCount,
    groupByDiscord,
  );
  const pageAccounts = progressive.visible;
  const filterKey = JSON.stringify([seasonId, releasePreferences, viewPool]);
  const previousFilter = useRef(filterKey);
  useEffect(() => {
    if (previousFilter.current !== filterKey) {
      setRenderCount(50);
      previousFilter.current = filterKey;
    }
  }, [filterKey]);
  const matchingTags = filtered.map((account) => account.tag);
  useStaffDetailsPage({
    seasonId,
    openDirect: (tag) => setEditingTag(tag),
  });
  const navigationTags = mode === "assign" ? matchingTags : detailsOrder;
  const hiddenTags = selectedTags.filter(
    (tag) => !pageAccounts.some((account) => account.tag === tag),
  );
  const hiddenSelection = selectedTags.filter(
    (tag) => !matchingTags.includes(tag),
  ).length;
  const unloadedSelection = hiddenTags.length - hiddenSelection;
  const panelHiddenTags = panelTags.filter(
    (tag) => !pageAccounts.some((account) => account.tag === tag),
  );
  const panelAccounts = panelTags
    .map((tag) => roster?.accounts.find((account) => account.tag === tag))
    .filter((account): account is NonNullable<typeof account> => !!account);
  const allMatchingSelected =
    matchingTags.length > 0 &&
    matchingTags.every((tag) => selectedTags.includes(tag));
  const toggleSelected = (tag: string) =>
    setSelectedTags((current) =>
      current.includes(tag)
        ? current.filter((item) => item !== tag)
        : [...current, tag],
    );
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
      !panelTags.length ||
      panelTags.length > 50
    )
      return false;
    const sid = seasonId;
    mutationPending.current = true;
    setBusy(true);
    setFeedback(null);
    try {
      await api(`/seasons/${encoded(sid)}/roster/assignments`, "PATCH", {
        revision: roster.revision,
        tags: panelTags,
        assigned_clan_tag: destination,
        include_locked: true,
      });
      if (activeSeason.current === sid)
        await afterWrite(
          destination
            ? "Accounts assigned. Placements locked."
            : "Accounts unassigned. Signups kept.",
          true,
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
    setUndoToast({
      status: "pending",
      label: placementMessage(undoReceipt.current.label, hasPublication),
    });
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
        await afterWrite("Last placement change undone.", true);
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
  const globalMissingWeight = releaseResult?.globalMissingWeightCount ?? 0;

  const clanName = (tag: string | null) =>
    roster?.clans.find((clan) => clan.tag === tag)?.name || tag || "Unassigned";

  useEffect(() => closeRosterActionMenus(), [seasonId, poolFilter, mode]);

  return (
    <div
      className={`roster-workspace roster-ui${mode === "assign" ? " roster-workspace-assign" : ""}`}
      onFocusCapture={(event) => {
        if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
          lastEditFocus.current = event.target;
          onEditFocus?.(event.target);
        }
      }}
    >
      {roster && panel === "assign" && (
        <RosterAssignPanel
          roster={roster}
          selectedAccounts={panelAccounts}
          hiddenTags={panelHiddenTags}
          busy={working}
          trigger={panelTrigger}
          onClose={closePanel}
          onAssign={assignSelected}
        />
      )}
      {roster && panel === "signup" && (
        <RosterSignupPanel
          accounts={panelAccounts}
          clans={roster.clans}
          hiddenTags={panelHiddenTags}
          busy={working}
          error={feedback?.kind === "error" ? feedback.text : undefined}
          trigger={panelTrigger}
          onClose={closePanel}
          onApply={bulkChangeSignups}
          onReviewChange={setSignupReviewOpen}
        />
      )}
      {(panel === "balance" || panel === "auto") && roster && (
        <RosterBalance
          roster={roster}
          seasonId={seasonId}
          tags={selectedTags}
          hiddenTags={hiddenTags}
          trigger={panelTrigger}
          automatic={panel === "auto"}
          pool={viewPool}
          onClose={closePanel}
          onBusy={setBusy}
          onPermissionError={(error) => void fail(error)}
          onSaved={async () => {
            await afterWrite("Placements applied. Signups unchanged.", true);
          }}
        />
      )}
      {undoToast && !panel && !editingTag && canRoster && (
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
          unloadedCount={unloadedSelection}
          busy={working}
          canRoster={canRoster}
          canSignups={canSignups}
          hidden={!!panel || !!editingTag || filterOpen || sortOpen}
          onAssign={(trigger) => openPanel("assign", trigger)}
          onBalance={(trigger) => openPanel("balance", trigger)}
          onSignup={(trigger) => openPanel("signup", trigger)}
          onClear={() => setSelectedTags([])}
          onHeight={setBarHeight}
        />
      )}
      {pendingLeave && (
        <ConfirmDialog
          key={pendingLeave.working ? "working" : "dirty"}
          heading={pendingLeave.working ? "Save in progress" : "Unsaved changes"}
          text={pendingLeave.working ? "Wait for the save to finish." : onlyWeightsDirty ? `You have ${weightsDirtyCount} unsaved weight${weightsDirtyCount === 1 ? "" : "s"}.` : "You have unsaved roster changes."}
          confirmLabel={pendingLeave.working ? "OK" : "Discard"}
          cancelLabel="Keep editing"
          hideCancel={pendingLeave.working}
          cancelOnBackdrop
          returnFocus={() => lastEditFocus.current}
          danger={!pendingLeave.working}
          onCancel={() => setPendingLeave(null)}
          onConfirm={() => {
            const { action, working: wasWorking } = pendingLeave;
            setPendingLeave(null);
            if (wasWorking) return;
            if (working) {
              setPendingLeave({ action: () => {}, working: true });
              return;
            }
            setWeightsDirtyCount(0);
            setWeightsDirty(false);
            setRulesDirty(false);
            setPlayerDirty(false);
            setSignupDirty(false);
            setSelectedTags([]);
            setEditingTag(null);
            closePanel();
            setDiscardToken((value) => value + 1);
            action();
          }}
        />
      )}
      <RosterHeader
        seasonId={seasonId}
        seasons={seasons}
        roster={roster}
        onPublication={(draft) => {
          setHasPublication(!!draft.published);
          onPublication?.(draft);
        }}
        pool={viewPool}
        canRoster={canRoster}
        canSignups={canSignups}
        canPublish={canPublish}
        uiLocked={uiLocked}
        navigationDisabled={uiLocked && !working}
        archived={!!archived}
        refreshKey={refreshEpoch}
        activeStatuses={mode === "assign" ? releasePreferences.statuses : []}
        onSeasonChange={(value) => {
          mayLeaveEditor(() => onSeasonChange(value));
        }}
        onRefresh={() => {
          mayLeaveEditor(() => {
            void refresh().catch((error) =>
              setFeedback({ kind: "error", text: errorText(error) }),
            );
          });
        }}
        onAutoPlace={(trigger) => {
          if (mode !== "assign") {
            mayLeaveEditor(() => {
              setReleasePreferences((current) => ({ ...current, pool: viewPool }));
              setMode("assign");
              openPanel("auto", trigger);
            });
          } else {
            openPanel("auto", trigger);
          }
        }}
        onFillSignupSpot={(item) => {
          if (!canRoster || (uiLocked && !working)) return false;
          if (working) { requestLeave(() => {}); return false; }
          requestSignupNavigation(() => {
            const pool = item.from_pool === "lazy" ? "lazy" : "main";
            try {
              if (item.assigned_clan_tag) {
                const key = `wu-compare-clans:${seasonId}:${pool}`;
                const available = sortClans(
                  assignmentOptions(roster?.clans ?? []).filter(
                    (clan) => clan.pool === pool,
                  ),
                  "name",
                ).map((clan) => clan.tag);
                const saved: unknown = JSON.parse(
                  localStorage.getItem(key) || "null",
                );
                const existing = comparisonOrder(saved, available);
                localStorage.setItem(
                  key,
                  JSON.stringify(
                    comparisonOrder(
                      [item.assigned_clan_tag, ...existing],
                      available,
                    ),
                  ),
                );
              }
            } catch {}
            setPoolFilter(pool);
            setSelectedTags([]);
            setCompareJump((value) => value + 1);
            setMode("compare");
            setEditingTag(null);
          });
          return true;
        }}
        onSignupDetails={(tag) => {
          if (uiLocked && !working) return false;
          if (working) { requestLeave(() => {}); return false; }
          requestSignupNavigation(() => {
            setSelectedTags([]);
            setFeedback(null);
            setEditingTag(tag);
          });
          return true;
        }}
        onFinalize={onReviewPublication}
        onCapacitySettings={(tag) => {
          if (uiLocked && !working) return;
          const clan = roster?.clans.find((item) => item.tag === tag);
          if (!clan) return;
          mayLeaveEditor(() => {
            setPoolFilter(clan.pool || "main");
            setFocusClanTag(tag);
            setFocusClanRequest((value) => value + 1);
            setMode("rules");
          });
        }}
        onStatusFilter={(status) => {
          const action = () => {
            setMode("assign");
            setReleasePreferences((current) => ({
              ...current,
              pool: status === "missing_weight" ? "all" : viewPool,
              search: "",
              statuses: status === "all" ? [] : [status],
              minWeight: null,
              maxWeight: null,
              townHalls: [],
              assignedClanTags: [],
            }));
          };
          if (mode !== "assign") mayLeaveEditor(action);
          else action();
        }}
        signupControls={
          season &&
          (canSignups || canSettings) && (
            <StaffSignupControls
              key={`${seasonId}:${discardToken}`}
              disabled={
                busy ||
                selectedTags.length > 0 ||
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
          )
        }
        onAccessError={(error) => void fail(error)}
      />
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
              ref={tabFades.ref}
              className="roster-workflow-nav has-horizontal-fades"
              data-fade-left={tabFades.left}
              data-fade-right={tabFades.right}
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
                    label: `Missing weights · ${globalMissingWeight}`,
                  },
                ] as const
              ).map((item) => (
                <Button
                  key={item.id}
                  disabled={uiLocked && !working}
                  aria-pressed={mode === item.id}
                  className={mode === item.id ? "active" : ""}
                  onClick={() => {
                    if (item.id === mode) return;
                    const action = () => {
                      setMode(item.id);
                      setSelectedTags([]);
                    };
                    mayLeaveEditor(action);
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
              aria-label="CWL account pool"
            >
              {(["all", "main", "lazy"] as const).map((pool) => (
                <Button
                  key={pool}
                  aria-pressed={releasePreferences.pool === pool}
                  disabled={uiLocked}
                  onClick={() =>
                    setReleasePreferences((current) => ({ ...current, pool }))
                  }
                >
                  {pool === "all"
                    ? "All accounts"
                    : pool === "main"
                      ? "Main CWL"
                      : "Lazy CWL"}
                </Button>
              ))}
            </div>
          ) : mode === "weights" ? null : (
            <CwlPoolTabs
              value={poolFilter}
              disabled={uiLocked && !working}
              onChange={(pool) => {
                mayLeaveEditor(() => {
                  setPoolFilter(pool);
                  closePanel();
                  setEditingTag(null);
                });
              }}
            />
          )}
          <div hidden={mode !== "assign"}>
            <RosterClanChips
              key={seasonId}
              roster={roster}
              pool={viewPool}
              selectedTags={releasePreferences.assignedClanTags}
              disabled={uiLocked}
              onSelect={(tag) =>
                setReleasePreferences((current) => ({
                  ...current,
                  assignedClanTags: current.assignedClanTags.includes(tag)
                    ? current.assignedClanTags.filter((item) => item !== tag)
                    : [...current.assignedClanTags, tag],
                }))
              }
            />
          </div>

          {canRoster && mode === "weights" && (
            <WeightQueue
              onOrderChange={setDetailsOrder}
              onClanWeights={onClanWeights}
              onDirty={setWeightsDirty}
              onDirtyCount={setWeightsDirtyCount}
              resetToken={discardToken}
              onEdit={(tag) => {
                setFeedback(null);
                requestDetailsNavigation(() => setEditingTag(tag));
              }}
              key={seasonId}
              accounts={roster.accounts}
              busy={busy}
              onRefresh={() => void refreshWeights()}
              archived={!!archived}
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
            <ClanSettings
              key={`${seasonId}:${discardToken}`}
              focusClanTag={focusClanTag}
              focusClanRequest={focusClanRequest}
              onFocusHandled={() => setFocusClanTag(null)}
              onHostingChanged={async () => {
                if (!(await refresh()))
                  throw new Error(
                    "Saved, but the roster could not refresh. Reload before making more changes.",
                  );
              }}
              onHostingBusy={setHostingBusy}
              onFamily={onFamilyClans}
              clans={roster.clans}
              accounts={roster.accounts}
              pool={poolFilter}
              busy={busy || hostingBusy}
              archived={!!archived}
              onPoolChange={setPoolFilter}
              onDirty={setRulesDirty}
              onLeave={mayLeaveEditor}
              onSave={saveRules}
            />
          )}
          {editingTag && roster.accounts.some((a) => a.tag === editingTag) && (
            <RosterPlayerDialog
              onClanWeights={onClanWeights}
              rosterUi
              onDirty={setPlayerDirty}
              key={seasonId}
              previous={
                navigationTags.indexOf(editingTag) > 0
                  ? () =>
                      setEditingTag(
                        navigationTags[navigationTags.indexOf(editingTag) - 1],
                      )
                  : undefined
              }
              next={
                navigationTags.indexOf(editingTag) >= 0 &&
                navigationTags.indexOf(editingTag) < navigationTags.length - 1
                  ? () =>
                      setEditingTag(
                        navigationTags[navigationTags.indexOf(editingTag) + 1],
                      )
                  : undefined
              }
              account={roster.accounts.find((a) => a.tag === editingTag)!}
              clans={roster.clans}
              roster={roster}
              locations={comparisonMemory.records}
              undo={
                undoToast && (
                  <RosterUndoToast
                    state={undoToast}
                    onUndo={() => void undoPlacement()}
                    onDismiss={() => setUndoToast(null)}
                  />
                )
              }
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
              onOrderChange={setDetailsOrder}
              memory={comparisonMemory}
              refreshKey={refreshEpoch}
              key={`${seasonId}:${compareJump}`}
              pool={poolFilter}
              seasonId={seasonId}
              roster={roster}
              busy={busy}
              onEdit={(tag) => {
                setFeedback(null);
                requestDetailsNavigation(() => setEditingTag(tag));
              }}
            />
          )}
          {mode === "assign" && (
            <>
              <RosterFilters
                onOpenChange={setFilterOpen}
                roster={roster}
                value={releasePreferences}
                disabled={uiLocked}
                onChange={(next) =>
                  setReleasePreferences((current) => ({ ...current, ...next }))
                }
              >
                <SortTrigger
                  ref={sortTrigger}
                  disabled={uiLocked || !!editingTag}
                  label={
                    rosterSortOptions.find(
                      ([value]) => value === releasePreferences.sort,
                    )?.[1] || "Unassigned first"
                  }
                  grouped={groupByDiscord}
                  aria-expanded={sortOpen}
                  onClick={() => setSortOpen(true)}
                />
                {sortOpen && (
                  <ActionPanel
                    title="Sort accounts"
                    trigger={sortTrigger.current}
                    className="roster-ui"
                    onClose={() => setSortOpen(false)}
                  >
                    <div className="roster-sort-options">
                      {rosterSortOptions.map(([value, label]) => (
                        <Button
                          key={value}
                          aria-pressed={releasePreferences.sort === value}
                          onClick={() => {
                            setReleasePreferences((current) => ({
                              ...current,
                              sort: value as RosterReleasePreferences["sort"],
                            }));
                            setSortOpen(false);
                          }}
                        >
                          {label}
                        </Button>
                      ))}
                      <label className="roster-group-toggle">
                        <input
                          type="checkbox"
                          checked={groupByDiscord}
                          disabled={uiLocked || !!editingTag}
                          onChange={(event) =>
                            setReleasePreferences((current) => ({
                              ...current,
                              grouped: event.target.checked,
                            }))
                          }
                        />
                        Group by Discord user
                      </label>
                    </div>
                  </ActionPanel>
                )}
              </RosterFilters>
              <div
                className="roster-list-heading"
                ref={listHeading}
                tabIndex={-1}
              >
                <label className="roster-select-all">
                  <input
                    type="checkbox"
                    checked={allMatchingSelected}
                    disabled={
                      uiLocked ||
                      archived ||
                      (!canRoster && !canSignups) ||
                      !matchingTags.length
                    }
                    onChange={(event) =>
                      setSelectedTags((current) =>
                        toggleAllRosterMatches(
                          current,
                          filtered,
                          event.target.checked,
                        ),
                      )
                    }
                  />{" "}
                  Select all {matchingTags.length} matching
                </label>
                <span>
                  {`${filtered.length} matching · ${selectedTags.length} selected`}
                </span>
              </div>
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
                      <RosterAccountCard
                        now={now}
                        account={account}
                        assignedClanName={clanName(account.assigned_clan_tag)}
                        showPool={viewPool === "all"}
                        selected={selectedTags.includes(account.tag)}
                        selectionMode={selectedTags.length > 0}
                        disabled={uiLocked}
                        canRoster={canRoster}
                        canSignups={canSignups}
                        archived={!!archived}
                        onToggle={() => toggleSelected(account.tag)}
                        onDetails={() => {
                          setFeedback(null);
                          requestDetailsNavigation(() =>
                            setEditingTag(account.tag),
                          );
                        }}
                        onAssign={(trigger) =>
                          openPanel("assign", trigger, [account.tag])
                        }
                        onSignup={(trigger) =>
                          openPanel("signup", trigger, [account.tag])
                        }
                      />
                    </Fragment>
                  ))}
                </div>
              ) : (
                <div className="card empty">
                  <p>No accounts match these filters.</p>
                </div>
              )}
              <div className="roster-load-more" aria-live="polite">
                <span>
                  Showing {pageAccounts.length} of {filtered.length} matching
                  accounts
                </span>
                {progressive.hasMore && (
                  <Button
                    disabled={uiLocked}
                    onClick={() => setRenderCount(progressive.nextCount)}
                  >
                    Load more
                  </Button>
                )}
              </div>
            </>
          )}
        </>
      )}
      {canPublish && (
        <button
          className="cwl-next-cue"
          disabled={uiLocked || !onReviewPublication}
          onClick={onReviewPublication}
        >
          Next: Finalize roster ›
        </button>
      )}
      <div
        className="roster-selection-spacer"
        style={{
          height: mode === "assign" && selectedTags.length ? barHeight + 24 : 0,
        }}
        aria-hidden="true"
      />
    </div>
  );
}
