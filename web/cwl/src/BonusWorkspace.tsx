import { monthSeasons, seasonMonthLabel } from "./seasonLabels";
import LoadError from "./LoadError";
import { participationSummary } from "./participation";
import "./rosterUi/tokens.css";
import CwlPageHeader from "./CwlPageHeader";
import useConfirmDialog from "./useConfirmDialog";
import { exportMonthLabel } from "./exportPreview";
import { countLabel } from "./countLabel";
import BonusHistory from "./BonusHistory";
import BonusHelpPanel from "./BonusHelpPanel";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import ActionMenu from "./rosterUi/ActionMenu";
import RosterMenu from "./rosterUi/Menu";
import { useDashboardPermission } from "./DashboardPermissions";
import { api, ApiError, type Pool, type Season } from "./api";
import CwlPoolTabs, { useCwlPool } from "./CwlPoolTabs";
import useUnsavedWork from "./useUnsavedWork";
import BonusStepBar, { bonusStepHref } from "./BonusStepBar";
import BonusCandidateReview from "./BonusCandidateReview";
import BonusStepPanel from "./BonusStepPanel";
import BonusResultsStep from "./BonusResultsStep";
import BonusRulesStep from "./BonusRulesStep";
import BonusAddCandidate from "./BonusAddCandidate";
import BonusDrawStep from "./BonusDrawStep";
import BonusApproveStep from "./BonusApproveStep";
import BonusAnnounceStep from "./BonusAnnounceStep";
import LazyAnnouncementCard from "./LazyAnnouncementCard";
import BonusClanSelect from "./BonusClanSelect";
import ResultsSettingsSheet, {
  type SettingsSaved,
} from "./ResultsSettingsSheet";
import {
  bonusStepStates,
  bonusSteps,
  loadBonusStatus,
  type BonusStatus,
  type BonusStep,
} from "./bonusStatus";
import { participationOutcome, resultDateText } from "./participationOutcome";
import {
  parseResultsState,
  plainClick,
  resultsStateQuery,
  type ResultsUrlState,
} from "./resultsUrlState";
import {
  bonusStepBlockers,
  reviewBlocked,
  canSaveBonusDraw,
  clanWideReasons,
  type BonusBlockerLine,
  type RaffleAccount,
  type RaffleData,
  type RafflePreview,
} from "./bonusRaffle";
import "./BonusWorkspace.css";

type Props = {
  seasonId: string;
  seasons: Season[];
  onDirty?: (dirty: boolean) => void;
  onSeasonChange: (id: string) => void;
  urlState?: string;
  onUrlState?: (state: string, push: boolean) => void;
  /** Opens the results list with pool, clan and outcome keys; absent without Results access. */
  onResults?: (state?: string) => void;
};

type PlayerLookup = {
  account: {
    tag: string;
    name: string;
    town_hall: number;
    current_clan_name?: string | null;
  };
};

function errorText(cause: unknown) {
  return cause instanceof Error
    ? cause.message
    : "The action could not be completed. Refresh to check its saved status.";
}

export default function BonusWorkspace({
  seasonId,
  seasons,
  onDirty,
  onSeasonChange,
  urlState = "",
  onUrlState,
  onResults,
}: Props) {
  const canManage = useDashboardPermission("cwl_bonuses");
  const initial = useRef(parseResultsState(urlState));
  const [storedPool, setStoredPool] = useCwlPool();
  const [urlPool, setUrlPool] = useState<Pool | undefined>(
    initial.current.pool,
  );
  const pool = urlPool || storedPool;
  const setPool = (next: Pool) => {
    setStoredPool(next);
    setUrlPool(next);
  };
  const [step, setStep] = useState<BonusStep | undefined>(initial.current.step);
  // An address with the steps marker waits for the page data to name its step.
  const [stepPending, setStepPending] = useState(
    !!initial.current.view && !initial.current.step,
  );
  // Where the page landed; typing a count must not move the open panel.
  const [landing, setLanding] = useState<BonusStep | undefined>();
  const [status, setStatus] = useState<BonusStatus | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [statusError, setStatusError] = useState("");
  const statusRequest = useRef(0);
  const emitted = useRef(urlState);
  const loadedSeason = useRef<string | null>(null);
  const [data, setData] = useState<RaffleData | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [clanTag, setClanTag] = useState(initial.current.clan || "");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const settingsTrigger = useRef<HTMLElement | null>(null);
  const countInput = useRef<HTMLInputElement | null>(null);
  const countDetails = useRef<HTMLDetailsElement | null>(null);
  const minimumInput = useRef<HTMLInputElement | null>(null);
  const flowSection = useRef<HTMLDivElement | null>(null);
  const [minimum, setMinimum] = useState("");
  const [slots, setSlots] = useState("");
  const [manualCount, setManualCount] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [preview, setPreview] = useState<RafflePreview | null>(null);
  const [reviewTag, setReviewTag] = useState("");
  const [reviewDirty, setReviewDirty] = useState(false);
  const [candidateOpen, setCandidateOpen] = useState(false);
  const [candidateTag, setCandidateTag] = useState("");
  const [candidateReason, setCandidateReason] = useState("");
  const [candidateLookup, setCandidateLookup] = useState<PlayerLookup | null>(
    null,
  );
  const [lookingUp, setLookingUp] = useState(false);
  const reviewOpener = useRef<HTMLElement | null>(null);
  const addOpener = useRef<HTMLButtonElement | null>(null);
  const candidateTagInput = useRef<HTMLInputElement | null>(null);
  const drawHeading = useRef<HTMLHeadingElement | null>(null);
  const previousStage = useRef<number | null>(null);
  const previewKeyRef = useRef("");
  const generation = useRef(0);
  const lookupGeneration = useRef(0);
  const lookupPending = useRef(false);
  const working = useRef(false);
  const activeSeason = useRef(seasonId);
  activeSeason.current = seasonId;
  const { confirm, dialog: confirmation } = useConfirmDialog(
    `${seasonId}:${canManage}:${data?.revision}:${busy}:${lookingUp}`,
  );
  const path = `/seasons/${encodeURIComponent(seasonId)}/bonus-raffle`;
  const archived = data?.season_status !== "draft";
  const policyDirty =
    pool === "main" && !!data && minimum !== String(data.policies.main ?? "");
  const formDirty =
    reviewDirty || (candidateOpen && !!(candidateTag || candidateReason));
  const unsaved =
    policyDirty ||
    formDirty ||
    (manualCount &&
      !!slots &&
      !data?.draws.some(
        (draw) =>
          draw.pool === pool &&
          draw.clan_tag === clanTag &&
          draw.cycle === data.cycle &&
          !draw.cancelled_at,
      ));
  useUnsavedWork(
    unsaved || settingsDirty || busy || lookingUp || !!cancelReason,
    onDirty,
  );

  const currentClans =
    data?.clans.filter((clan) =>
      data.accounts.some(
        (account) =>
          account.pool === pool && account.assigned_clan_tag === clan.tag,
      ),
    ) || [];
  const clans =
    pool === "lazy"
      ? [
          ...(data?.lazy_hosts || []),
          ...currentClans.filter(
            (clan) => !data?.lazy_hosts?.some((host) => host.tag === clan.tag),
          ),
        ]
      : [...currentClans];
  for (const saved of data?.draws || []) {
    if (
      saved.pool === pool &&
      saved.cycle === data?.cycle &&
      !saved.cancelled_at &&
      !clans.some((clan) => clan.tag === saved.clan_tag)
    ) {
      clans.push({
        tag: saved.clan_tag,
        name: `${saved.snapshot.clan_name} · Saved draw`,
        slots: saved.snapshot.slots,
      });
    }
  }
  const selectedClan = clans.find((clan) => clan.tag === clanTag);
  const draw = data?.draws.find(
    (item) =>
      item.pool === pool &&
      item.clan_tag === clanTag &&
      item.cycle === data.cycle &&
      !item.cancelled_at,
  );
  const allowance = data?.allowances?.[clanTag];
  const statusSummary = participationSummary(
    data?.accounts.filter(
      (account) =>
        account.pool === pool &&
        (!clanTag || account.assigned_clan_tag === clanTag),
    ) || [],
    data?.sync,
  );
  const requestedSlots = manualCount ? Number(slots) : null;
  const countReady = manualCount
    ? /^\d+$/.test(slots) && Number(slots) >= 1 && Number(slots) <= 50
    : allowance?.status === "ready";
  const clanAccounts =
    data?.accounts.filter(
      (account) =>
        account.pool === pool && account.assigned_clan_tag === clanTag,
    ) || [];
  const reviewAccount = clanAccounts.find(
    (account) => account.tag === reviewTag,
  );
  const hostStatus = status?.pools[pool].find((item) => item.tag === clanTag);
  const leagueMissing = !allowance?.league;
  const savedMinimum = data?.policies.main ?? null;
  const typedMinimum =
    /^\d+$/.test(minimum) && Number(minimum) <= 7 ? Number(minimum) : null;
  const minimumPreview =
    pool === "main" && policyDirty && typedMinimum !== null;
  const chipMinimum = minimumPreview ? typedMinimum : savedMinimum;

  // Did not join is a final result, never a missing one.
  const resultAccounts = clanAccounts.filter(
    (account) => !account.did_not_join,
  );
  // A saved staff reason covers a player with nothing captured.
  const unchecked = resultAccounts.filter(
    (account) =>
      (account.attacks === null || !account.source_complete) &&
      !(
        account.attacks === null &&
        account.stars === null &&
        account.bonus_review?.override_reason
      ),
  );
  const allMissing =
    resultAccounts.length > 0 &&
    resultAccounts.every(
      (account) => account.attacks === null || !account.source_complete,
    );
  const clanWide = clanWideReasons(clanAccounts);
  const canReviewUnchecked = pool === "lazy" && canManage && !archived;
  const hostInactive =
    (!!hostStatus && !hostStatus.active) ||
    clanWide.includes("Hosting clan is not an active Lazy clan this season");
  const blockers = bonusStepBlockers({
    canManage,
    archived: !!archived,
    policyDirty,
    reviewDirty,
    candidateOpen,
    countReady: !!countReady,
    needsMinimum: pool === "main" && data?.policies.main === null,
    resultsMissing:
      unchecked.length > 0 &&
      (allMissing || clanWide.includes("Results not captured")),
    uncheckedCount: unchecked.length,
    canReviewUnchecked,
    cycleMissing: !!data && !data.cycle,
    hostInactive,
  });

  // Step states come from the page's own data; the status read fills the gaps.
  const drawState = !draw
    ? "none"
    : draw.delivery?.status === "sent"
      ? "sent"
      : draw.approved_at
        ? "approved"
        : "saved";
  const drawn = drawState !== "none";
  const stepDone: Record<BonusStep, boolean> = {
    results:
      drawn ||
      (clanAccounts.length
        ? unchecked.length === 0
        : hostStatus?.results_state === "captured"),
    rules:
      drawn ||
      ((pool !== "main" || data?.policies.main != null) &&
        !!countReady &&
        !hostInactive),
    draw: drawn,
    approve: drawState === "approved" || drawState === "sent",
    announce: drawState === "sent",
  };
  const stepInput = {
    done: stepDone,
    reasons: Object.fromEntries(
      bonusSteps.map((item) => [
        item.id,
        blockers[item.id].find((line) => line.bar && line.id !== "archived")
          ?.text || "",
      ]),
    ) as Partial<Record<BonusStep, string>>,
  };
  const stepViews = bonusStepStates(
    hostStatus || null,
    pool,
    data?.policies.main ?? null,
    stepInput,
  );
  const defaultStep: BonusStep =
    stepViews.find((view) => view.state !== "done")?.id || "announce";
  const openStep = step || landing || defaultStep;
  // Draw, Approve and Announce wait for every step before them.
  const gateFor = (id: BonusStep) => {
    const index = bonusSteps.findIndex((item) => item.id === id);
    const waiting = stepViews
      .slice(0, index)
      .find((view) => view.state !== "done");
    return waiting ? `Finish ${waiting.label} first.` : "";
  };
  const drawGate = gateFor("draw");
  // The page notice says "Archived season" once; no step repeats it.
  const stepLines = (id: BonusStep) =>
    blockers[id].filter((line) => line.id !== "archived");
  const firstBlocking = (id: BonusStep) =>
    stepLines(id).find((line) => line.blocks)?.text || "";
  const previewAllowed =
    !!data &&
    !!selectedClan &&
    !draw &&
    !drawGate &&
    !reviewBlocked(blockers.draw);

  const openSettings = () => {
    settingsTrigger.current = document.querySelector<HTMLElement>(
      ".bonus-context .roster-action-trigger",
    );
    setSettingsOpen(true);
  };
  // Incomplete players open Results filtered to them when they share one outcome.
  const incompleteOutcomes = new Set(
    (preview?.excluded || [])
      .filter((account) => !account.did_not_join && !account.source_complete)
      .map((account) => participationOutcome(account, data?.policies.main))
      .filter((outcome) => outcome === "partial" || outcome === "not_checked"),
  );
  const incompleteLink = bonusStepHref(
    seasonId,
    "results",
    pool,
    clanTag,
    incompleteOutcomes.size === 1 ? [...incompleteOutcomes][0] : undefined,
  );
  const openIncomplete = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!plainClick(event) || !onResults) return;
    event.preventDefault();
    onResults(incompleteLink.query);
  };
  const focusField = (field: HTMLElement | null) => {
    field?.scrollIntoView?.({ block: "center" });
    field?.focus({ preventScroll: true });
  };
  const checkClashDisabled =
    !canManage ||
    busy ||
    lookingUp ||
    !!archived ||
    policyDirty ||
    reviewDirty ||
    candidateOpen ||
    !data?.cycle;
  const checkClash = () =>
    void mutate(
      "/refresh-results",
      {},
      "CWL check finished. Review this clan’s status before drawing.",
    );
  const blockerFix = (line: BonusBlockerLine): ReactNode => {
    const action = (
      onClick: () => void,
      text = line.text,
      disabled = false,
    ) => (
      <button
        type="button"
        className="bonus-inline-action"
        disabled={disabled}
        onClick={onClick}
      >
        {text}
      </button>
    );
    switch (line.id) {
      case "count":
        return action(() => {
          if (!leagueMissing && countDetails.current) {
            countDetails.current.open = true;
            setManualCount(true);
          }
          requestAnimationFrame(() => focusField(countInput.current));
        });
      case "minimum":
      case "minimum-dirty":
        return action(() => focusField(minimumInput.current));
      case "open-review":
        return action(() =>
          focusField(
            document.querySelector<HTMLElement>(
              ".bonus-review-editor, .bonus-add-candidate",
            ),
          ),
        );
      case "results":
        return (
          <>
            {line.text} ·{" "}
            {action(checkClash, "Check Clash now", checkClashDisabled)}
          </>
        );
      case "partial":
        return canReviewUnchecked ? (
          <>
            {unchecked.length} not checked ·{" "}
            {action(() => void openFirstUnchecked(), "Review")}
          </>
        ) : (
          <>
            {line.text} ·{" "}
            {action(checkClash, "Check Clash now", checkClashDisabled)}
          </>
        );
      case "cycle":
        return onResults ? (
          <>
            {line.text} · {action(openSettings, "Open Settings")}
          </>
        ) : (
          line.text
        );
      case "inactive":
        return <>{line.text} · Set its season pool in Build roster</>;
      default:
        return line.text;
    }
  };
  const stage = draw?.approved_at ? 3 : draw ? 2 : preview ? 1 : 0;
  useEffect(() => {
    if (previousStage.current === 1 && stage === 2) {
      requestAnimationFrame(() =>
        drawHeading.current?.focus({ preventScroll: true }),
      );
    }
    previousStage.current = stage;
  }, [stage]);

  useEffect(() => {
    if (data && selectedClan && !landing) setLanding(defaultStep);
  }, [data, selectedClan?.tag, landing]);
  const clearPreview = () => {
    previewKeyRef.current = "";
    setPreview(null);
  };
  const resetContext = (source = data, nextPool = pool) => {
    lookupGeneration.current += 1;
    lookupPending.current = false;
    setLookingUp(false);
    setMinimum(String(source?.policies[nextPool] ?? ""));
    setManualCount(false);
    setLanding(undefined);
    clearPreview();
    setSlots("");
    setCancelReason("");
    setReviewTag("");
    setReviewDirty(false);
    setCandidateOpen(false);
    setCandidateTag("");
    setCandidateReason("");
    setCandidateLookup(null);
    setNotice("");
  };

  const loadStatus = useCallback(async () => {
    const id = ++statusRequest.current;
    const sid = seasonId;
    setStatusFailed(false);
    setStatusError("");
    try {
      const result = await loadBonusStatus(sid);
      if (id !== statusRequest.current || activeSeason.current !== sid) return;
      setStatus(result);
    } catch (cause) {
      if (id !== statusRequest.current || activeSeason.current !== sid) return;
      setStatus(null);
      setStatusFailed(true);
      setStatusError(cause instanceof Error ? cause.message : "");
    }
  }, [seasonId]);
  const load = useCallback(async () => {
    if (!seasonId || working.current) return;
    working.current = true;
    const request = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const result = await api<RaffleData>(path);
      if (request !== generation.current) return;
      setData(result);
      clearPreview();
      // The step bar and clan states read after the list, never before it.
      void loadStatus();
    } catch (cause) {
      if (request !== generation.current) return;
      setData(null);
      setError(errorText(cause));
    } finally {
      if (request === generation.current) {
        working.current = false;
        setBusy(false);
      }
    }
  }, [path, seasonId, loadStatus]);

  useEffect(() => {
    generation.current += 1;
    statusRequest.current += 1;
    working.current = false;
    setData(null);
    setStatus(null);
    setStatusFailed(false);
    // The first visit keeps the clan and step from the URL.
    if (loadedSeason.current !== null && loadedSeason.current !== seasonId) {
      setClanTag("");
      setStep(undefined);
      const query = resultsStateQuery({ pool });
      emitted.current = query;
      onUrlState?.(query, false);
    }
    loadedSeason.current = seasonId;
    setError("");
    resetContext(null);
    void load();
    return () => {
      generation.current += 1;
    };
  }, [load]);
  // Back, Forward and shared links restore pool, clan and step.
  useEffect(() => {
    if (urlState === emitted.current) return;
    emitted.current = urlState;
    const next = parseResultsState(urlState);
    if (next.pool && next.pool !== pool) {
      setPool(next.pool);
      resetContext(data, next.pool);
    }
    // An address with no clan shows the clan cards only.
    if ((next.clan || "") !== clanTag) {
      setClanTag(next.clan || "");
      resetContext(data, next.pool || pool);
    }
    setStep(next.step);
    setStepPending(!!next.view && !next.step);
  }, [urlState]);
  const emit = (
    next: {
      pool?: Pool;
      clan?: string;
      step?: BonusStep;
      view?: "steps";
    },
    push = true,
  ) => {
    const query = resultsStateQuery({
      pool: next.pool ?? pool,
      clan: "clan" in next ? next.clan || undefined : clanTag || undefined,
      step: "step" in next ? next.step : step,
      view: next.view,
    });
    emitted.current = query;
    onUrlState?.(query, push);
  };
  // The steps view always carries a step; the page's own data names it.
  useEffect(() => {
    if (!stepPending || !data || !selectedClan) return;
    setStepPending(false);
    setStep(defaultStep);
    emit({ step: defaultStep }, false);
  }, [stepPending, data, selectedClan?.tag, defaultStep]);
  // After a saved action the page follows the first step that is not done.
  const followFlow = () => {
    setLanding(undefined);
    if (step === undefined) return;
    setStep(undefined);
    setStepPending(true);
    emit({ step: undefined, view: "steps" }, false);
  };
  const openStepTo = (target: BonusStep, pick?: ResultsUrlState) => {
    setStep(target);
    emit(
      pick
        ? { pool: pick.pool, clan: pick.clan, step: target }
        : { step: target },
    );
    flowSection.current?.scrollIntoView?.({ block: "start" });
  };
  useEffect(() => {
    if (candidateOpen) candidateTagInput.current?.focus();
  }, [candidateOpen]);
  useEffect(() => {
    if (data) setMinimum(String(data.policies[pool] ?? ""));
  }, [data, pool]);
  // A clan from another pool or season is dropped; no clan shows the cards only.
  useEffect(() => {
    if (data && clanTag && !clans.some((clan) => clan.tag === clanTag))
      setClanTag("");
  }, [data, pool, clanTag]);

  const mutate = async (
    suffix: string,
    body: unknown,
    success: string,
    method = "POST",
  ) => {
    if (working.current || archived) return false;
    working.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    const request = ++generation.current;
    const sid = seasonId;
    try {
      const result = await api<RaffleData>(path + suffix, method, body);
      if (request !== generation.current || activeSeason.current !== sid)
        return false;
      setData(result);
      clearPreview();
      setCancelReason("");
      setNotice(success);
      void loadStatus();
      return true;
    } catch (cause) {
      if (request !== generation.current) return false;
      if (cause instanceof ApiError && [401, 403].includes(cause.status))
        setData(null);
      clearPreview();
      setError(errorText(cause));
      return false;
    } finally {
      if (request === generation.current) {
        working.current = false;
        setBusy(false);
      }
    }
  };
  const canDiscard = async () =>
    (!unsaved && !cancelReason) ||
    (await confirm("Discard unsaved bonus edits?", "Discard bonus edits"));
  const canLeaveEditor = async () =>
    (!reviewDirty && !(candidateOpen && (candidateTag || candidateReason))) ||
    (await confirm(
      "Discard unsaved candidate edits?",
      "Discard candidate edits",
    ));
  const refresh = async () => {
    if (!working.current && !lookupPending.current && (await canDiscard())) {
      resetContext();
      void load();
    }
  };
  const allClans = async () => {
    if (!clanTag || !(await canDiscard())) return;
    if (onResults) {
      onResults(resultsStateQuery({ pool }));
      return;
    }
    setClanTag("");
    setStep(undefined);
    resetContext();
    emit({ clan: undefined, step: undefined });
  };
  // Read-only: the draw preview. It never writes.
  const review = async () => {
    if (
      working.current ||
      !selectedClan ||
      policyDirty ||
      reviewDirty ||
      candidateOpen ||
      !countReady ||
      archived
    )
      return;
    working.current = true;
    const key = previewKey;
    previewKeyRef.current = key;
    setBusy(true);
    setError("");
    setPreview(null);
    const request = ++generation.current;
    // A change of clan, pool, step setup or data clears the key; that preview is dropped.
    const current = () =>
      request === generation.current && previewKeyRef.current === key;
    try {
      const result = await api<RafflePreview>(path + "/preview", "POST", {
        pool,
        clan_tag: clanTag,
        slots: requestedSlots,
      });
      if (current()) setPreview(result);
    } catch (cause) {
      if (current()) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          setData(null);
        setError(errorText(cause));
      }
    } finally {
      if (request === generation.current) {
        working.current = false;
        setBusy(false);
      }
    }
  };
  // The Draw step loads its preview once per setup; any change clears it.
  const previewKey = `${seasonId}:${pool}:${clanTag}:${requestedSlots}:${data?.revision}`;
  useEffect(() => {
    if (
      openStep !== "draw" ||
      !previewAllowed ||
      preview ||
      busy ||
      lookingUp ||
      previewKeyRef.current === previewKey
    )
      return;
    void review();
  }, [openStep, previewAllowed, preview, busy, lookingUp, previewKey]);
  const lookupCandidate = async () => {
    if (!candidateTag.trim() || lookingUp || lookupPending.current) return;
    const lookup = ++lookupGeneration.current;
    lookupPending.current = true;
    const lookupSeason = seasonId;
    setLookingUp(true);
    setCandidateLookup(null);
    setError("");
    try {
      const result = await api<PlayerLookup>(
        `/seasons/${encodeURIComponent(seasonId)}/staff-signups/player?tag=${encodeURIComponent(candidateTag.trim())}`,
      );
      if (
        lookup === lookupGeneration.current &&
        lookupSeason === activeSeason.current
      )
        setCandidateLookup(result);
    } catch (cause) {
      if (
        lookup === lookupGeneration.current &&
        lookupSeason === activeSeason.current
      ) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          setData(null);
        setError(errorText(cause));
      }
    } finally {
      if (lookup === lookupGeneration.current) {
        lookupPending.current = false;
        setLookingUp(false);
      }
    }
  };
  // The Review panel returns focus to the control that opened it.
  const closeReview = () => {
    setReviewTag("");
    setReviewDirty(false);
  };
  const closeCandidate = () => {
    setCandidateOpen(false);
    setCandidateTag("");
    setCandidateReason("");
    setCandidateLookup(null);
    requestAnimationFrame(() =>
      addOpener.current?.focus({ preventScroll: true }),
    );
  };
  const openReview = async (
    account: RaffleAccount,
    opener: HTMLElement | null,
  ) => {
    if (!(await canLeaveEditor())) return;
    setCandidateOpen(false);
    setCandidateTag("");
    setCandidateReason("");
    setCandidateLookup(null);
    reviewOpener.current = opener;
    setReviewTag(account.tag);
    clearPreview();
    setError("");
  };
  const openFirstUnchecked = async () => {
    if (unchecked[0]) await openReview(unchecked[0], null);
  };
  const locked = !canManage || busy || !!archived || !!draw;
  const meetsRule =
    pool === "main" && chipMinimum === null
      ? null
      : clanAccounts.filter(
          (account) => participationOutcome(account, chipMinimum) === "meets",
        ).length;
  const total = draw
    ? draw.snapshot.slots
    : manualCount && countReady
      ? Number(slots)
      : allowance?.status === "ready"
        ? allowance.total
        : null;
  const summaries: Record<BonusStep, string> = {
    results: `${clanAccounts.length} ${clanAccounts.length === 1 ? "player" : "players"}${
      pool === "main" && savedMinimum === null
        ? ""
        : `, ${
            clanAccounts.filter(
              (account) =>
                participationOutcome(account, savedMinimum) === "meets",
            ).length
          } meet rule`
    }`,
    rules: `${
      pool === "main" && savedMinimum !== null
        ? `Minimum ${savedMinimum} attacks · `
        : ""
    }${total ?? "?"} bonuses`,
    draw: `${countLabel(draw?.snapshot.winners.length ?? 0, "winner")} saved`,
    approve: "Winners approved",
    announce: "Announcement sent",
  };
  const panel = (id: BonusStep, children: ReactNode) => {
    const view = stepViews.find((item) => item.id === id)!;
    return (
      <BonusStepPanel
        key={id}
        id={id}
        number={bonusSteps.findIndex((item) => item.id === id) + 1}
        label={view.label}
        state={view.state}
        open={openStep === id}
        summary={summaries[id]}
        onChange={() => openStepTo(id)}
        headingRef={drawHeading}
      >
        {children}
      </BonusStepPanel>
    );
  };
  const staleWarning = statusSummary.warning;
  const staleText =
    staleWarning === "These results have not been checked recently." &&
    data?.sync.last_checked_at
      ? `Results not checked since ${resultDateText(data.sync.last_checked_at)}`
      : staleWarning;

  return (
    <div className="bonus-workspace roster-ui">
      {confirmation}
      <CwlPageHeader
        className="bonus-page-head"
        title={<h1>Results &amp; bonuses</h1>}
        help={<BonusHelpPanel />}
      >
        <RosterMenu
          label="Season"
          value={seasonId}
          disabled={busy || lookingUp}
          onValueChange={async (id) => {
            if (id !== seasonId && (await canDiscard())) onSeasonChange(id);
          }}
          options={[
            { value: "", label: "Select a season" },
            ...monthSeasons(seasons).map((season) => ({
              value: String(season.id),
              label: seasonMonthLabel(season),
            })),
          ]}
        />
      </CwlPageHeader>
      {data && (
        <div className="bonus-context">
          <p>
            {/* An unset month is said once, by the Results blocker. */}
            {data.cycle && (
              <>
                <strong>{exportMonthLabel(data.cycle)}</strong> ·{" "}
              </>
            )}
            {data.sync.last_checked_at
              ? `Clash checked ${resultDateText(data.sync.last_checked_at)}`
              : "Clash not checked yet"}
          </p>
          <ActionMenu
            name="Bonus results"
            items={[
              {
                id: "refresh",
                label: "Refresh",
                disabled: busy || lookingUp,
                onAction: () => void refresh(),
              },
              {
                id: "refresh-results",
                label: "Check Clash now",
                disabled: checkClashDisabled,
                onAction: checkClash,
              },
              {
                id: "settings",
                label: "Settings",
                disabled: busy || lookingUp,
                onAction: openSettings,
              },
            ]}
          />
        </div>
      )}
      {seasonId && selectedClan && (
        <BonusStepBar
          seasonId={seasonId}
          pool={pool}
          clan={clanTag}
          status={status}
          failed={statusFailed}
          onRetry={() => void loadStatus()}
          input={data ? stepInput : undefined}
          resultsInPage
          canOpen={() => true}
          onSelect={async (target, query) => {
            const next = parseResultsState(query);
            const moved =
              (next.pool && next.pool !== pool) ||
              (next.clan && next.clan !== clanTag);
            if (moved && !(await canDiscard())) return;
            if (next.pool && next.pool !== pool) setPool(next.pool);
            if (next.clan && next.clan !== clanTag) setClanTag(next.clan);
            if (moved) resetContext(data, next.pool || pool);
            // The red "Review" reason opens the first player who needs it.
            const reviewNow =
              target === "results" &&
              canReviewUnchecked &&
              !draw &&
              stepViews[0].state === "blocked" &&
              blockers.results.some((line) => line.id === "partial");
            openStepTo(target, next);
            if (reviewNow) await openFirstUnchecked();
          }}
        />
      )}
      {error && !(data && (candidateOpen || reviewAccount)) && (
        <div className="notice error" role="alert">
          {error}{" "}
          <button type="button" disabled={busy} onClick={refresh}>
            Refresh saved status
          </button>
        </div>
      )}
      {notice && <p role="status">{notice}</p>}
      {busy && (
        <p className="working-status" role="status">
          Working…
        </p>
      )}
      {!seasonId && <p>Select a season to begin.</p>}
      {data && (
        <>
          <CwlPoolTabs
            value={pool}
            disabled={busy || lookingUp}
            onChange={async (next) => {
              if (await canDiscard()) {
                setPool(next);
                resetContext(data, next);
                emit({ pool: next, clan: undefined, step: undefined });
              }
            }}
          />
          {clans.length > 0 && (
            <BonusClanSelect
              clans={clans}
              selected={clanTag || "all"}
              pool={pool}
              status={status}
              opensSteps
              disabled={busy || lookingUp}
              onChange={async (tag) => {
                if (tag === "all") return allClans();
                if (tag === clanTag || !(await canDiscard())) return;
                // The page data names the step once it loads, so the status
                // read and the open step never disagree.
                setClanTag(tag);
                setStep(undefined);
                setStepPending(true);
                resetContext();
                emit({ clan: tag, step: undefined, view: "steps" });
              }}
            />
          )}
          {!clans.length && (
            <p>
              No current signups are assigned to a hosting clan in this CWL
              pool.
            </p>
          )}
          {pool === "lazy" && status && (
            <LazyAnnouncementCard
              seasonId={seasonId}
              clans={status.pools.lazy}
              clanTag={clanTag}
              archived={!!archived}
              disabled={busy || lookingUp}
              onSent={() => void loadStatus()}
            />
          )}
          {pool === "lazy" && !selectedClan && statusFailed && (
            <LoadError
              message={statusError || "Lazy announcement could not load."}
              onRetry={() => void loadStatus()}
            />
          )}
          {archived && <p className="notice">Archived season · Read only</p>}
          {!data.sync.enabled && onResults && (
            <p className="notice error" role="alert">
              <span>
                Automatic CWL capture is off. Enable it in Settings to retain
                results ·{" "}
                <button
                  type="button"
                  className="bonus-inline-action"
                  onClick={openSettings}
                >
                  Open Settings
                </button>
              </span>
            </p>
          )}
          {staleText && (
            <p className="notice bonus-stale" role="status">
              {staleText}&nbsp;·{" "}
              <button
                type="button"
                className="bonus-inline-action"
                disabled={checkClashDisabled}
                onClick={checkClash}
              >
                Check Clash now
              </button>
            </p>
          )}

          {selectedClan && (
            <div
              ref={flowSection}
              className="bonus-step-panels"
              aria-busy={busy}
            >
              <h2 className="bonus-clan-heading">{selectedClan.name}</h2>
              {panel(
                "results",
                <BonusResultsStep
                  lines={blockers.results}
                  fix={blockerFix}
                  accounts={clanAccounts}
                  minimum={savedMinimum}
                  onReview={
                    pool === "lazy"
                      ? (account, opener) => void openReview(account, opener)
                      : undefined
                  }
                  busy={busy || !canManage || !!archived}
                />,
              )}
              {panel(
                "rules",
                <BonusRulesStep
                  pool={pool}
                  sitOutMonths={
                    data.sit_out_settings?.find((row) => row.tag === clanTag)
                      ?.months ?? 3
                  }
                  lines={stepLines("rules")}
                  fix={blockerFix}
                  locked={locked}
                  minimum={minimum}
                  minimumInput={minimumInput}
                  minimumPreview={minimumPreview}
                  canSaveMinimum={
                    canManage &&
                    !busy &&
                    !archived &&
                    !draw &&
                    !reviewDirty &&
                    !candidateOpen &&
                    policyDirty &&
                    typedMinimum !== null
                  }
                  onMinimum={(value) => {
                    setMinimum(value);
                    clearPreview();
                  }}
                  onSaveMinimum={() =>
                    void mutate(
                      "/policy",
                      {
                        pool,
                        minimum: Number(minimum),
                        revision: data.revision,
                      },
                      "Minimum attacks saved. Earlier draws stay unchanged.",
                      "PATCH",
                    )
                  }
                  allowance={allowance}
                  leagueMissing={leagueMissing}
                  slots={slots}
                  manualCount={manualCount}
                  countReady={!!countReady}
                  countInput={countInput}
                  countDetails={countDetails}
                  onSlots={(value) => {
                    setSlots(value);
                    clearPreview();
                  }}
                  onManualCount={(value) => {
                    setManualCount(value);
                    clearPreview();
                  }}
                  accounts={clanAccounts}
                  chipMinimum={chipMinimum}
                  meetsRule={meetsRule}
                  onReview={
                    pool === "lazy"
                      ? (account, opener) => void openReview(account, opener)
                      : undefined
                  }
                  listBusy={busy || !canManage || !!archived}
                  addCandidate={
                    pool === "lazy" && !draw ? (
                      <BonusAddCandidate
                        open={candidateOpen}
                        disabled={!canManage || busy || !!archived}
                        busy={busy}
                        lookingUp={lookingUp}
                        canManage={canManage}
                        error={error}
                        tag={candidateTag}
                        reason={candidateReason}
                        lookup={candidateLookup}
                        openerRef={addOpener}
                        tagInputRef={candidateTagInput}
                        onToggle={() => {
                          setCandidateOpen((current) => !current);
                          setCandidateLookup(null);
                          setError("");
                        }}
                        onTag={(value) => {
                          setCandidateTag(value);
                          setCandidateLookup(null);
                        }}
                        onReason={setCandidateReason}
                        onFind={() => void lookupCandidate()}
                        onCancel={async () => {
                          if (await canLeaveEditor()) closeCandidate();
                        }}
                        onAdd={() =>
                          void (async () => {
                            if (
                              await mutate(
                                "/manual-candidates",
                                {
                                  tag: candidateLookup!.account.tag,
                                  clan_tag: clanTag,
                                  reason: candidateReason.trim(),
                                  revision: data.revision,
                                },
                                "Candidate added. Check the draw again before saving.",
                              )
                            ) {
                              closeCandidate();
                            }
                          })()
                        }
                      />
                    ) : null
                  }
                />,
              )}
              {panel(
                "draw",
                <BonusDrawStep
                  pool={pool}
                  gate={drawGate}
                  blocker={firstBlocking("draw")}
                  draw={draw}
                  preview={preview}
                  busy={busy}
                  minimum={data.policies.main}
                  canSave={
                    !!preview &&
                    canSaveBonusDraw({
                      canManage,
                      busy,
                      archived: !!archived,
                      policyDirty,
                      reviewDirty,
                      reviewOpen: !!reviewTag,
                      candidateOpen,
                      lookingUp,
                      blocked: !!preview.blocking_reasons.length,
                    })
                  }
                  reasonFix={(reason) =>
                    reason.startsWith("Resolve incomplete") && onResults ? (
                      <>
                        {" · "}
                        <a href={incompleteLink.href} onClick={openIncomplete}>
                          Check these players
                        </a>
                      </>
                    ) : null
                  }
                  onDraw={() =>
                    void mutate(
                      "/draw",
                      {
                        pool,
                        clan_tag: clanTag,
                        slots: requestedSlots,
                        fingerprint: preview!.fingerprint,
                      },
                      "Winners saved. Review before approving.",
                    ).then((saved) => saved && followFlow())
                  }
                />,
              )}
              {panel(
                "approve",
                <BonusApproveStep
                  gate={gateFor("approve")}
                  blocker={firstBlocking("approve")}
                  draw={draw}
                  disabled={!canManage || busy || !!archived}
                  cancelDisabled={
                    !canManage || busy || !!archived || !cancelReason.trim()
                  }
                  cancelReason={cancelReason}
                  onCancelReason={setCancelReason}
                  onApprove={() =>
                    void mutate(
                      `/${draw!.id}/approve`,
                      {},
                      "Winners approved. Review the announcement and select a channel.",
                    ).then((saved) => saved && followFlow())
                  }
                  onCancel={() =>
                    void mutate(
                      `/${draw!.id}/cancel`,
                      { reason: cancelReason.trim() },
                      "Draw cancelled. It stays in history.",
                    ).then((saved) => saved && followFlow())
                  }
                />,
              )}
              {panel(
                "announce",
                <BonusAnnounceStep
                  gate={gateFor("announce")}
                  draw={draw}
                  disabled={busy || !!archived}
                  onSend={(channel, retry = false) =>
                    void mutate(
                      `/${draw!.id}/send`,
                      { channel_id: channel, retry },
                      "Delivery status updated below.",
                    )
                  }
                />,
              )}
              {reviewAccount && (
                <BonusCandidateReview
                  key={reviewAccount.tag}
                  account={reviewAccount}
                  trigger={reviewOpener.current}
                  busy={busy}
                  readOnly={!!draw}
                  onDirty={setReviewDirty}
                  onCancel={async () => {
                    if (await canLeaveEditor()) closeReview();
                  }}
                  onRemove={
                    reviewAccount.manual_candidate
                      ? async () => {
                          if (
                            !(await confirm(
                              `Remove ${reviewAccount.player_name} from this bonus candidate pool? The CWL signup and roster will stay unchanged.`,
                              "Remove candidate",
                            ))
                          )
                            return;
                          if (
                            await mutate(
                              "/manual-candidates",
                              {
                                tag: reviewAccount.tag,
                                revision: data.revision,
                              },
                              "Manual candidate removed. Check the draw again before saving.",
                              "DELETE",
                            )
                          ) {
                            closeReview();
                          }
                        }
                      : undefined
                  }
                  error={error}
                  onSave={async (flags, overrideReason) => {
                    const saved = await mutate(
                      "/account-review",
                      {
                        tag: reviewAccount.tag,
                        flags,
                        override_reason: overrideReason,
                        revision: data.revision,
                      },
                      `Infractions saved · ${selectedClan?.name || "Hosting clan"} eligibility updated.`,
                      "PATCH",
                    );
                    if (saved) closeReview();
                    return saved;
                  }}
                />
              )}
            </div>
          )}
          {/* Exports holds the history for anyone who can open it. */}
          {!onResults && (
            <BonusHistory key={`bonus:${seasonId}`} seasonId={seasonId} />
          )}
        </>
      )}
      {settingsOpen && seasonId && (
        <ResultsSettingsSheet
          seasonId={seasonId}
          canCapture={!!onResults}
          canOdds={canManage}
          archived={!!archived}
          trigger={settingsTrigger.current}
          onDirty={setSettingsDirty}
          onClose={() => setSettingsOpen(false)}
          onSaved={(saved: SettingsSaved) => {
            void saved;
            void load();
          }}
        />
      )}
    </div>
  );
}
