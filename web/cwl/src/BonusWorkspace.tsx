import { participationSummary } from "./participation";
import "./rosterUi/tokens.css";
import CwlPageHeader from "./CwlPageHeader";
import useConfirmDialog from "./useConfirmDialog";
import { exportMonthLabel } from "./exportPreview";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { TriangleAlert } from "lucide-react";
import ActionMenu from "./rosterUi/ActionMenu";
import { useDashboardPermission } from "./DashboardPermissions";
import { api, ApiError, type Pool, type Season } from "./api";
import CwlPoolTabs, { useCwlPool } from "./CwlPoolTabs";
import useUnsavedWork from "./useUnsavedWork";
import useChoiceRail from "./useChoiceRail";
import BonusAnnouncement from "./BonusAnnouncement";
import BonusStepBar, { bonusStepHref } from "./BonusStepBar";
import SearchPicker from "./SearchPicker";
import { roleOption } from "./RolePicker";
import { StatusPill } from "./rosterUi/primitives";
import BonusCandidateReview, { LAZY_FLAGS } from "./BonusCandidateReview";
import {
  bonusClanState,
  loadBonusStatus,
  type BonusStatus,
  type BonusStep,
} from "./bonusStatus";
import {
  countText,
  outcomeLabels,
  outcomeTone,
  participationOutcome,
  resultDateText,
} from "./participationOutcome";
import {
  parseResultsState,
  plainClick,
  resultsStateQuery,
} from "./resultsUrlState";
import {
  attacksText,
  bonusCandidateStatus,
  bonusReviewBlockers,
  reviewBlocked,
  canSaveBonusDraw,
  clanWideReasons,
  playerReasons,
  type BonusListMode,
  type BonusReviewBlocker,
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
  /** Opens Results with pool and clan keys; absent without Results access. */
  onResults?: (state?: string) => void;
};

const CLAN_SEARCH_MIN = 8;

type Role = { id: string; name: string };
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

function AccountList({
  accounts,
  onReview,
  busy,
  searchable = false,
  mode = "candidates",
  minimum = null,
}: {
  accounts: RaffleAccount[];
  onReview?: (account: RaffleAccount, opener: HTMLButtonElement) => void;
  busy?: boolean;
  searchable?: boolean;
  mode?: BonusListMode;
  minimum?: number | null;
}) {
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(20);
  const matching = useMemo(
    () =>
      accounts.filter((account) =>
        `${account.player_name} ${account.tag}`
          .toLowerCase()
          .includes(query.trim().toLowerCase()),
      ),
    [accounts, query],
  );

  return (
    <div className="bonus-account-results">
      {searchable && (
        <label className="bonus-account-search">
          Find an account
          <input
            type="search"
            name="account-search"
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setVisibleCount(20);
            }}
            placeholder="Player name or tag"
          />
        </label>
      )}
      <ul className="bonus-account-list">
        {matching
          .slice(0, searchable ? visibleCount : matching.length)
          .map((account) => {
            const outcome = participationOutcome(account, minimum);
            // Clan-wide reasons show once in the clan notice, not per row.
            const reasons = account.exclusion
              ? playerReasons(account)
              : [bonusCandidateStatus(account, mode)].filter(Boolean);
            return (
              <li key={account.tag}>
                <div className="bonus-account-identity">
                  <strong>{account.player_name}</strong>
                  <small>
                    {account.tag}
                    {account.manual_candidate ? " · Added by staff" : ""}
                  </small>
                </div>
                <div className="bonus-account-outcome">
                  <strong>
                    {attacksText(account)}
                    {account.stars !== null
                      ? ` · ${countText(account.stars, "star")}`
                      : ""}
                  </strong>
                  {(outcome || reasons.length > 0) && (
                    <span className="bonus-account-state">
                      {outcome && (
                        <StatusPill
                          tone={outcomeTone(outcome)}
                          className="bonus-outcome"
                        >
                          {outcomeLabels[outcome]}
                        </StatusPill>
                      )}
                      {reasons.length > 0 && (
                        <small className="bonus-account-reason">
                          {reasons.join(" · ")}
                        </small>
                      )}
                    </span>
                  )}
                  {account.multiplier === 2 && <small>2× ticket weight</small>}
                  {!!account.bonus_review?.flags.length && (
                    <small>
                      {account.bonus_review.flags
                        .map(
                          (flag) =>
                            LAZY_FLAGS.find((item) => item.id === flag)
                              ?.label || flag,
                        )
                        .join(" · ")}
                    </small>
                  )}
                </div>
                {onReview && (
                  <button
                    type="button"
                    className="bonus-quiet-action"
                    disabled={busy}
                    onClick={(event) => onReview(account, event.currentTarget)}
                  >
                    Review
                    <span className="sr-only"> {account.player_name}</span>
                  </button>
                )}
              </li>
            );
          })}
      </ul>
      {searchable && matching.length > visibleCount && (
        <button
          type="button"
          className="bonus-show-more"
          onClick={() => setVisibleCount((count) => count + 20)}
        >
          Show 20 more · {matching.length - visibleCount} remaining
        </button>
      )}
      {!matching.length && (
        <p className="bonus-empty">
          {query
            ? "No accounts match this search."
            : "No accounts in this group."}
        </p>
      )}
    </div>
  );
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
  const [status, setStatus] = useState<BonusStatus | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const statusRequest = useRef(0);
  const emitted = useRef(urlState);
  const loadedSeason = useRef<string | null>(null);
  const [data, setData] = useState<RaffleData | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [clanTag, setClanTag] = useState(initial.current.clan || "");
  const [clanQuery, setClanQuery] = useState("");
  const clanRail = useChoiceRail<HTMLDivElement>(clanTag);
  const countInput = useRef<HTMLInputElement | null>(null);
  const countDetails = useRef<HTMLDetailsElement | null>(null);
  const minimumInput = useRef<HTMLInputElement | null>(null);
  const roleDetails = useRef<HTMLDetailsElement | null>(null);
  const flowSection = useRef<HTMLElement | null>(null);
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
  const [roleId, setRoleId] = useState("");
  const [roles, setRoles] = useState<Role[]>([]);
  const [rolesError, setRolesError] = useState("");
  const [rolesLoading, setRolesLoading] = useState(false);
  const reviewOpener = useRef<HTMLButtonElement | null>(null);
  const addOpener = useRef<HTMLButtonElement | null>(null);
  const candidateTagInput = useRef<HTMLInputElement | null>(null);
  const candidateHeading = useRef<HTMLHeadingElement | null>(null);
  const drawHeading = useRef<HTMLHeadingElement | null>(null);
  const previousStage = useRef<number | null>(null);
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
  const roleDirty =
    pool === "lazy" &&
    !!data &&
    roleId !==
      (data.lazy_settings?.representative_role_id || "769130325460254740");
  const formDirty =
    reviewDirty ||
    (candidateOpen && !!(candidateTag || candidateReason)) ||
    roleDirty;
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
  useUnsavedWork(unsaved || busy || lookingUp || !!cancelReason, onDirty);

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
  const rolesUnavailable =
    pool === "lazy" &&
    clanAccounts.some(
      (account) => account.representative_status === "unavailable",
    );
  const resultsMissing =
    clanAccounts.length > 0 &&
    clanAccounts.every(
      (account) => account.attacks === null || !account.source_complete,
    );
  const blockers = bonusReviewBlockers({
    canManage,
    archived: !!archived,
    policyDirty,
    roleDirty,
    reviewDirty,
    candidateOpen,
    countReady,
    needsMinimum: pool === "main" && data?.policies.main === null,
    rolesUnavailable,
    resultsMissing,
  });
  // A reason that covers the whole clan shows once, above the list.
  const clanNotices = [
    ...new Set([
      ...(hostStatus && !hostStatus.active
        ? ["Hosting clan is not an active Lazy clan this season"]
        : []),
      ...clanWideReasons(clanAccounts),
      ...(resultsMissing ? ["Results not captured"] : []),
      ...(rolesUnavailable ? ["Discord roles unavailable"] : []),
    ]),
  ];
  const resultsLink = bonusStepHref(seasonId, "results", pool, clanTag);
  const openResults = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!plainClick(event) || !onResults) return;
    event.preventDefault();
    onResults(resultsLink.query);
  };
  const focusField = (field: HTMLElement | null) => {
    field?.scrollIntoView?.({ block: "center" });
    field?.focus({ preventScroll: true });
  };
  const blockerFix = (blocker: { id: BonusReviewBlocker; text: string }) => {
    const action = (onClick: () => void, text = blocker.text) => (
      <button type="button" className="bonus-inline-action" onClick={onClick}>
        {text}
      </button>
    );
    switch (blocker.id) {
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
      case "role-dirty":
        return action(() => {
          if (roleDetails.current) roleDetails.current.open = true;
          focusField(roleDetails.current);
        });
      case "open-review":
        return action(() =>
          focusField(
            document.querySelector<HTMLElement>(
              ".bonus-review-editor, .bonus-add-candidate",
            ),
          ),
        );
      case "roles":
        return (
          <>
            Discord roles unavailable · {action(() => void refresh(), "Retry")}
          </>
        );
      case "results":
        return onResults ? (
          <a href={resultsLink.href} onClick={openResults}>
            {blocker.text}
          </a>
        ) : (
          blocker.text
        );
      default:
        return blocker.text;
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

  const resetContext = (source = data, nextPool = pool) => {
    lookupGeneration.current += 1;
    lookupPending.current = false;
    setLookingUp(false);
    setMinimum(String(source?.policies[nextPool] ?? ""));
    setRoleId(
      source?.lazy_settings?.representative_role_id || "769130325460254740",
    );
    setManualCount(false);
    setPreview(null);
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
    try {
      const result = await loadBonusStatus(sid);
      if (id !== statusRequest.current || activeSeason.current !== sid) return;
      setStatus(result);
    } catch {
      if (id !== statusRequest.current || activeSeason.current !== sid) return;
      setStatus(null);
      setStatusFailed(true);
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
      setPreview(null);
      setRoleId(
        result.lazy_settings?.representative_role_id || "769130325460254740",
      );
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
    if (next.clan && next.clan !== clanTag) {
      setClanTag(next.clan);
      resetContext(data, next.pool || pool);
    }
    setStep(next.step);
  }, [urlState]);
  const emit = (
    next: { pool?: Pool; clan?: string; step?: BonusStep },
    push = true,
  ) => {
    const query = resultsStateQuery({
      pool: next.pool ?? pool,
      clan: "clan" in next ? next.clan || undefined : clanTag || undefined,
      step: "step" in next ? next.step : step,
    });
    emitted.current = query;
    onUrlState?.(query, push);
  };
  useEffect(() => {
    if (candidateOpen) candidateTagInput.current?.focus();
  }, [candidateOpen]);
  useEffect(() => {
    if (data) setMinimum(String(data.policies[pool] ?? ""));
  }, [data, pool]);
  useEffect(() => {
    if (data && !clans.some((clan) => clan.tag === clanTag))
      setClanTag(clans[0]?.tag || "");
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
      setPreview(null);
      setCancelReason("");
      setNotice(success);
      void loadStatus();
      return true;
    } catch (cause) {
      if (request !== generation.current) return false;
      if (cause instanceof ApiError && [401, 403].includes(cause.status))
        setData(null);
      setPreview(null);
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
  const review = async () => {
    if (
      working.current ||
      !selectedClan ||
      policyDirty ||
      roleDirty ||
      reviewDirty ||
      candidateOpen ||
      !countReady ||
      archived
    )
      return;
    working.current = true;
    setBusy(true);
    setError("");
    setPreview(null);
    const request = ++generation.current;
    try {
      const result = await api<RafflePreview>(path + "/preview", "POST", {
        pool,
        clan_tag: clanTag,
        slots: requestedSlots,
      });
      if (request === generation.current) setPreview(result);
    } catch (cause) {
      if (request === generation.current) {
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
  const closeReview = () => {
    setReviewTag("");
    setReviewDirty(false);
    const opener = reviewOpener.current;
    requestAnimationFrame(() =>
      (opener?.isConnected ? opener : candidateHeading.current)?.focus({
        preventScroll: true,
      }),
    );
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
  const loadRoles = async () => {
    if (roles.length || rolesLoading) return;
    setRolesLoading(true);
    setRolesError("");
    try {
      const result = await api<{ roles: Role[] }>("/announcement-roles");
      setRoles(result.roles);
    } catch (cause) {
      setRolesError(errorText(cause));
    } finally {
      setRolesLoading(false);
    }
  };

  // One compact line per clan-wide reason: icon, text and its fix.
  const clanNotice = selectedClan && clanNotices.length > 0 && (
    <div className="notice bonus-clan-notice" role="status">
      {clanNotices.map((text) => (
        <p key={text}>
          <TriangleAlert size={16} aria-hidden="true" />
          <span>
            {text}
            {text === "Results not captured" && (
              <>
                {" · "}
                {onResults ? (
                  <a href={resultsLink.href} onClick={openResults}>
                    Open Results
                  </a>
                ) : (
                  "Check Results & participation"
                )}
              </>
            )}
            {text.startsWith("Hosting clan") && (
              <> · Set its season pool in Build roster</>
            )}
            {text === "Discord roles unavailable" && (
              <>
                {" · "}
                <button
                  type="button"
                  className="bonus-inline-action"
                  disabled={busy || lookingUp}
                  onClick={refresh}
                >
                  Retry
                </button>
              </>
            )}
          </span>
        </p>
      ))}
    </div>
  );

  return (
    <div className="bonus-workspace roster-ui">
      {confirmation}
      <CwlPageHeader className="bonus-page-head" title={<h1>Bonus medals</h1>}>
        <label className="bonus-season">
          Season
          <select
            name="season"
            autoComplete="off"
            value={seasonId}
            disabled={busy || lookingUp}
            onChange={async (event) => {
              const id = event.target.value;
              if (id !== seasonId && (await canDiscard())) onSeasonChange(id);
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
      </CwlPageHeader>
      {data && (
        <div className="bonus-context">
          <p>
            <strong>
              {data.cycle ? exportMonthLabel(data.cycle) : "CWL month not set"}
            </strong>{" "}
            ·{" "}
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
                label: "Refresh attacks from Clash",
                disabled:
                  !canManage ||
                  busy ||
                  lookingUp ||
                  archived ||
                  policyDirty ||
                  roleDirty ||
                  reviewDirty ||
                  candidateOpen ||
                  !data.cycle,
                onAction: () =>
                  void mutate(
                    "/refresh-results",
                    {},
                    "CWL check finished. Review this clan’s status before drawing.",
                  ),
              },
            ]}
          />
        </div>
      )}
      {seasonId && (
        <BonusStepBar
          seasonId={seasonId}
          pool={pool}
          clan={clanTag}
          status={status}
          failed={statusFailed}
          onRetry={() => void loadStatus()}
          canOpen={(target) => target !== "results" || !!onResults}
          onSelect={async (target, query) => {
            if (target === "results") {
              onResults?.(query);
              return;
            }
            const next = parseResultsState(query);
            const moved =
              (next.pool && next.pool !== pool) ||
              (next.clan && next.clan !== clanTag);
            if (moved && !(await canDiscard())) return;
            if (next.pool && next.pool !== pool) setPool(next.pool);
            if (next.clan && next.clan !== clanTag) setClanTag(next.clan);
            if (moved) resetContext(data, next.pool || pool);
            setStep(target);
            emit({ pool: next.pool, clan: next.clan, step: target });
            flowSection.current?.scrollIntoView?.({ block: "start" });
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
          {archived && <p className="notice">Archived season · Read only</p>}
          {!data.cycle && (
            <p className="notice">
              Select this season’s CWL month in Results &amp; participation
              first.
            </p>
          )}
          {!data.sync.enabled && (
            <p className="notice error" role="alert">
              <span>
                Automatic CWL capture is off. Enable checks in{" "}
                <a
                  href={`/cwl/results?season=${encodeURIComponent(seasonId)}`}
                  onClick={(event) => {
                    // Ctrl/Cmd and middle selection open a new tab untouched.
                    if (!plainClick(event) || (!unsaved && !cancelReason))
                      return;
                    event.preventDefault();
                    const href = event.currentTarget.href;
                    void canDiscard().then((allowed) => {
                      if (allowed) window.location.assign(href);
                    });
                  }}
                >
                  Participation
                </a>{" "}
                to retain results.
              </span>
            </p>
          )}
          {statusSummary.warning && (
            <p className="notice" role="status">
              {statusSummary.warning}
            </p>
          )}
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
          {clans.length >= CLAN_SEARCH_MIN && (
            <label className="bonus-clan-search">
              Find a clan
              <input
                type="search"
                name="clan-search"
                autoComplete="off"
                spellCheck={false}
                value={clanQuery}
                onChange={(event) => setClanQuery(event.target.value)}
              />
            </label>
          )}
          {clans.length > 0 && (
            <div
              {...clanRail.fadeProps}
              ref={clanRail.ref}
              className="bonus-clan-cards has-horizontal-fades"
              role="group"
              aria-label="Hosting clan"
            >
              {clans
                .filter(
                  (clan) =>
                    clan.tag === clanTag ||
                    clan.name
                      .toLowerCase()
                      .includes(clanQuery.trim().toLowerCase()),
                )
                .map((clan) => {
                  const state = status?.pools[pool].find(
                    (item) => item.tag === clan.tag,
                  );
                  return (
                    <button
                      type="button"
                      key={clan.tag}
                      className="bonus-clan-card"
                      aria-pressed={clan.tag === clanTag}
                      disabled={busy || lookingUp}
                      onClick={async () => {
                        if (clan.tag === clanTag || !(await canDiscard()))
                          return;
                        setClanTag(clan.tag);
                        resetContext();
                        emit({ clan: clan.tag, step: undefined });
                      }}
                    >
                      <strong>{clan.name}</strong>
                      <small>
                        {state
                          ? `${
                              state.meets_rule === null
                                ? countText(state.candidates, "candidate")
                                : `${state.meets_rule} of ${state.candidates} meet`
                            } · ${bonusClanState(state)}`
                          : statusFailed
                            ? clan.tag
                            : "…"}
                      </small>
                    </button>
                  );
                })}
            </div>
          )}
          {!clans.length && (
            <p>
              No current signups are assigned to a hosting clan in this CWL
              pool.
            </p>
          )}

          {selectedClan && !draw && (
            <section ref={flowSection} className="bonus-flow" aria-busy={busy}>
              <div className="bonus-section-heading bonus-clan-heading">
                <h2>{selectedClan.name}</h2>
              </div>
              {clanNotice}
              <div className="bonus-stats">
                {leagueMissing ? (
                  <label className="bonus-inline-count">
                    <span>Bonuses shown in Clash</span>
                    <input
                      ref={countInput}
                      type="number"
                      name="bonus-count"
                      autoComplete="off"
                      inputMode="numeric"
                      min="1"
                      max="50"
                      step="1"
                      value={slots}
                      disabled={!canManage || busy || archived}
                      onChange={(event) => {
                        setManualCount(true);
                        setSlots(event.target.value);
                        setPreview(null);
                      }}
                    />
                  </label>
                ) : (
                  <div>
                    <strong>
                      {manualCount && countReady
                        ? Number(slots)
                        : allowance?.status === "ready"
                          ? allowance.total
                          : "—"}
                    </strong>
                    <span>
                      Total bonus allowance
                      {manualCount && countReady ? " · staff count" : ""}
                    </span>
                  </div>
                )}
                <div>
                  <strong>{clanAccounts.length}</strong>
                  <span>Current candidates</span>
                </div>
                <div role="status">
                  <strong>
                    {preview?.eligible.length ??
                      (pool === "lazy"
                        ? clanAccounts.filter((account) => !account.exclusion)
                            .length
                        : "—")}
                  </strong>
                  <span>
                    {preview
                      ? "Verified eligible"
                      : pool === "lazy"
                        ? "Meets rules now"
                        : "Qualifying"}
                  </span>
                </div>
              </div>
              {pool === "main" ? (
                <div className="bonus-policy">
                  <label>
                    Minimum attacks
                    <input
                      ref={minimumInput}
                      type="number"
                      name="minimum-attacks"
                      autoComplete="off"
                      inputMode="numeric"
                      min="0"
                      max="7"
                      step="1"
                      value={minimum}
                      disabled={!canManage || busy || archived}
                      onChange={(event) => {
                        setMinimum(event.target.value);
                        setPreview(null);
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={
                      !canManage ||
                      busy ||
                      archived ||
                      reviewDirty ||
                      candidateOpen ||
                      !policyDirty ||
                      !/^\d+$/.test(minimum) ||
                      Number(minimum) > 7
                    }
                    onClick={() =>
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
                  >
                    Save minimum
                  </button>
                </div>
              ) : (
                <>
                  <div className="bonus-candidates-heading">
                    <h3 ref={candidateHeading} tabIndex={-1}>
                      Candidate review
                    </h3>
                  </div>
                  <AccountList
                    accounts={clanAccounts}
                    minimum={data.policies.main}
                    onReview={async (account, opener) => {
                      if (await canLeaveEditor()) {
                        setCandidateOpen(false);
                        setCandidateTag("");
                        setCandidateReason("");
                        setCandidateLookup(null);
                        reviewOpener.current = opener;
                        setReviewTag(account.tag);
                        setPreview(null);
                        setError("");
                      }
                    }}
                    busy={busy || !canManage || archived}
                    searchable
                  />
                  {reviewAccount && (
                    <BonusCandidateReview
                      key={reviewAccount.tag}
                      account={reviewAccount}
                      busy={busy}
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
                                  "Manual candidate removed. Review eligibility again.",
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
                          "Account review saved. Review eligibility again before drawing.",
                          "PATCH",
                        );
                        if (saved) closeReview();
                        return saved;
                      }}
                    />
                  )}
                </>
              )}

              <div className="bonus-action-bar">
                <button
                  type="button"
                  className="primary"
                  aria-describedby={
                    blockers.length ? "bonus-review-blockers" : undefined
                  }
                  disabled={busy || reviewBlocked(blockers)}
                  onClick={() => void review()}
                >
                  Review eligibility
                </button>
              </div>
              {blockers.length > 0 && (
                <ul id="bonus-review-blockers" className="bonus-blockers">
                  {blockers.map((blocker) => (
                    <li key={blocker.id}>{blockerFix(blocker)}</li>
                  ))}
                </ul>
              )}
              {preview && (
                <section className="bonus-preview" aria-label="Draw preview">
                  <div className="bonus-section-heading">
                    <h3>
                      {preview.eligible.length} eligible ·{" "}
                      {Math.min(preview.available, preview.eligible.length)}{" "}
                      winners
                    </h3>
                    <span>{preview.available} slots remaining</span>
                  </div>
                  <p>
                    {preview.allowance_source === "automatic"
                      ? "Calculated"
                      : "Staff-confirmed"}{" "}
                    allowance · {preview.slots} total bonuses
                    {pool === "main" && preview.minimum !== null
                      ? ` · Minimum ${preview.minimum} attacks`
                      : ""}
                  </p>
                  {preview.available >= preview.eligible.length && (
                    <p>
                      Every eligible account will win. Unused slots remain open.
                    </p>
                  )}
                  {!!preview.blocking_reasons.length && (
                    <div className="notice error" role="alert">
                      {preview.blocking_reasons.map((reason) => (
                        <p key={reason}>{reason}</p>
                      ))}
                      <p>Refresh the results before you draw.</p>
                    </div>
                  )}
                  <h4>In the draw</h4>
                  <AccountList
                    accounts={preview.eligible}
                    mode="eligible"
                    minimum={data.policies.main}
                  />
                  <details className="bonus-secondary">
                    <summary>Excluded ({preview.excluded.length})</summary>
                    <AccountList
                      accounts={preview.excluded}
                      mode="excluded"
                      minimum={data.policies.main}
                    />
                  </details>
                  <div className="bonus-action-bar">
                    <span>Saved draws cannot be redrawn by refreshing.</span>
                    <button
                      type="button"
                      className="primary"
                      disabled={
                        !canSaveBonusDraw({
                          canManage,
                          busy,
                          archived: !!archived,
                          policyDirty,
                          roleDirty,
                          reviewDirty,
                          reviewOpen: !!reviewTag,
                          candidateOpen,
                          lookingUp,
                          blocked: !!preview.blocking_reasons.length,
                        })
                      }
                      onClick={() =>
                        void mutate(
                          "/draw",
                          {
                            pool,
                            clan_tag: clanTag,
                            slots: requestedSlots,
                            fingerprint: preview.fingerprint,
                          },
                          "Winners saved. Review before approving.",
                        )
                      }
                    >
                      {preview.available >= preview.eligible.length
                        ? "Save all winners"
                        : "Draw and save winners"}
                    </button>
                  </div>
                </section>
              )}
              {pool === "lazy" && (
                <div className="bonus-support">
                  <strong>Bonus rules</strong>
                  <ol>
                    <li>Follow the Lazy CWL rules.</li>
                    <li>
                      Play 60% of the event: 4+ attacks, or 3 attacks and 8+
                      stars.
                    </li>
                    <li>No bonus in the previous 3 seasons.</li>
                  </ol>
                  <p>Bonuses from before the dashboard are not recorded.</p>
                </div>
              )}
              <details ref={countDetails} className="bonus-secondary">
                <summary>Bonus count and source</summary>
                <p className="bonus-allowance-reason">
                  {allowance?.reason ||
                    "Refresh Clash results to check the allowance."}
                </p>
                <p>
                  {allowance?.league || "League unknown"}
                  {allowance?.team_size
                    ? ` · ${allowance.team_size} vs ${allowance.team_size}`
                    : ""}{" "}
                  · {allowance?.completed_wars ?? 0}/{allowance?.rounds ?? "?"}{" "}
                  wars complete
                  {allowance?.base != null
                    ? ` · ${allowance.base} base + ${allowance.wins} wins${allowance.status === "ready" ? ` = ${allowance.total}` : ""}`
                    : ""}
                </p>
                <label className="bonus-check">
                  <input
                    type="checkbox"
                    name="manual-count"
                    checked={manualCount}
                    disabled={!canManage || busy || archived}
                    onChange={(event) => {
                      setManualCount(event.target.checked);
                      setPreview(null);
                    }}
                  />
                  <span>Use the total shown in Clash</span>
                </label>
                {manualCount && !leagueMissing && (
                  <label>
                    Total bonuses shown in Clash
                    <input
                      ref={countInput}
                      type="number"
                      name="bonus-count"
                      autoComplete="off"
                      inputMode="numeric"
                      min="1"
                      max="50"
                      step="1"
                      value={slots}
                      disabled={!canManage || busy || archived}
                      onChange={(event) => {
                        setSlots(event.target.value);
                        setPreview(null);
                      }}
                    />
                  </label>
                )}
                {manualCount && (
                  <p className="bonus-caution">
                    Staff-confirmed count; not API-verified.
                  </p>
                )}
              </details>
              {pool === "lazy" && (
                <>
                  <div className="bonus-candidates-heading">
                    <button
                      ref={addOpener}
                      type="button"
                      disabled={!canManage || busy || archived}
                      onClick={() => {
                        setCandidateOpen((current) => !current);
                        setCandidateLookup(null);
                        setError("");
                      }}
                    >
                      Add player by tag
                    </button>
                  </div>
                  {candidateOpen && (
                    <section
                      className="bonus-add-candidate"
                      aria-label="Add bonus candidate"
                    >
                      <p>
                        Add an account directly to this clan’s candidate pool.
                        This does not change its signup or roster placement.
                      </p>
                      <div className="bonus-lookup">
                        <label>
                          Player tag
                          <input
                            ref={candidateTagInput}
                            name="player-tag"
                            autoComplete="off"
                            spellCheck={false}
                            value={candidateTag}
                            maxLength={20}
                            disabled={busy || lookingUp}
                            placeholder="#PLAYER"
                            onChange={(event) => {
                              setCandidateTag(event.target.value);
                              setCandidateLookup(null);
                            }}
                          />
                        </label>
                        <button
                          type="button"
                          disabled={!candidateTag.trim() || busy || lookingUp}
                          onClick={() => void lookupCandidate()}
                        >
                          {lookingUp ? "Looking up…" : "Find player"}
                        </button>
                      </div>
                      {candidateLookup && (
                        <p>
                          <strong>{candidateLookup.account.name}</strong> ·{" "}
                          {candidateLookup.account.tag} · TH{" "}
                          {candidateLookup.account.town_hall}
                          {candidateLookup.account.current_clan_name
                            ? ` · ${candidateLookup.account.current_clan_name}`
                            : ""}
                        </p>
                      )}
                      <label>
                        Reason for addition
                        <textarea
                          name="candidate-reason"
                          autoComplete="off"
                          value={candidateReason}
                          maxLength={500}
                          disabled={busy}
                          onChange={(event) =>
                            setCandidateReason(event.target.value)
                          }
                          placeholder="Why should this player enter this clan’s draw?"
                        />
                      </label>
                      {error && (
                        <p className="notice error" role="alert">
                          {error}
                        </p>
                      )}
                      <div className="bonus-editor-actions">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={async () => {
                            if (await canLeaveEditor()) closeCandidate();
                          }}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          className="primary"
                          disabled={
                            !canManage ||
                            busy ||
                            !candidateLookup ||
                            !candidateReason.trim()
                          }
                          onClick={() =>
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
                                  "Candidate added. Review eligibility before drawing.",
                                )
                              ) {
                                closeCandidate();
                              }
                            })()
                          }
                        >
                          Add candidate
                        </button>
                      </div>
                    </section>
                  )}
                  <details
                    ref={roleDetails}
                    className="bonus-secondary"
                    onToggle={(event) => {
                      if (event.currentTarget.open) void loadRoles();
                    }}
                  >
                    <summary>FWA Rep odds settings</summary>
                    <p>
                      Members with this Discord role get 2 chances in Lazy
                      draws. Each account can win only one time. With 2 chances,
                      an account does not always have twice the chance to win
                      when the draw picks more than one winner.
                    </p>
                    {rolesLoading && <p role="status">Loading roles…</p>}
                    {rolesError && (
                      <p role="alert">
                        {rolesError}{" "}
                        <button type="button" onClick={() => void loadRoles()}>
                          Retry roles
                        </button>
                      </p>
                    )}
                    <SearchPicker
                      label="Representative role"
                      value={roleId}
                      options={roles.map(roleOption)}
                      fallback={{
                        value: roleId,
                        label: "Saved role (not found)",
                      }}
                      disabled={busy || archived || !canManage}
                      placeholder="Select a role"
                      searchPlaceholder="Search roles"
                      emptyText="No roles match."
                      onChange={(id) => {
                        setRoleId(id);
                        setPreview(null);
                      }}
                    />
                    <button
                      type="button"
                      disabled={
                        !canManage ||
                        busy ||
                        archived ||
                        reviewDirty ||
                        candidateOpen ||
                        !roleDirty ||
                        !/^\d{15,22}$/.test(roleId)
                      }
                      onClick={() =>
                        void mutate(
                          "/lazy-settings",
                          {
                            representative_role_id: roleId,
                            revision: data.revision,
                          },
                          "Representative role saved. Review eligibility again before drawing.",
                          "PATCH",
                        )
                      }
                    >
                      Save role
                    </button>
                  </details>
                </>
              )}
            </section>
          )}

          {draw && (
            <section className="bonus-flow" aria-busy={busy}>
              <div className="bonus-section-heading">
                <div>
                  <h2 ref={drawHeading} tabIndex={-1}>
                    {draw.snapshot.clan_name} · Bonus medals
                  </h2>
                  <p>
                    Saved {resultDateText(draw.created_at)} ·{" "}
                    {draw.approved_at ? "Approved" : "Awaiting staff approval"}
                  </p>
                </div>
              </div>
              {clanNotice}
              <div className="bonus-stats">
                <div>
                  <strong>{draw.snapshot.winners.length}</strong>
                  <span>Winners</span>
                </div>
                <div>
                  <strong>{draw.snapshot.eligible.length}</strong>
                  <span>Eligible</span>
                </div>
                <div>
                  <strong>{draw.snapshot.slots}</strong>
                  <span>Bonus allowance</span>
                </div>
              </div>
              <AccountList
                accounts={draw.snapshot.winners}
                mode="winners"
                minimum={draw.snapshot.minimum}
              />
              <details className="bonus-secondary">
                <summary>Draw details and all eligible accounts</summary>
                <p>
                  {draw.snapshot.allowance_source === "automatic"
                    ? "Calculated"
                    : "Staff-confirmed"}{" "}
                  allowance · Saved results do not change if the rules change
                  later.
                </p>
                <AccountList
                  accounts={draw.snapshot.eligible}
                  mode="eligible"
                  minimum={draw.snapshot.minimum}
                />
              </details>
              {!draw.approved_at && (
                <div className="bonus-action-bar">
                  <span>
                    Approval records the winners. It does not send a message.
                  </span>
                  <button
                    type="button"
                    className="primary"
                    disabled={!canManage || busy || archived}
                    onClick={() =>
                      void mutate(
                        `/${draw.id}/approve`,
                        {},
                        "Winners approved. Review the announcement and select a channel.",
                      )
                    }
                  >
                    Approve winners
                  </button>
                </div>
              )}
              {!draw.approved_at && (
                <details className="bonus-secondary">
                  <summary>Cancel this draw</summary>
                  <p>
                    Cancel only if the results or setup are wrong. The winners
                    and the reason stay in history.
                  </p>
                  <label>
                    Reason
                    <textarea
                      name="cancel-reason"
                      autoComplete="off"
                      maxLength={500}
                      value={cancelReason}
                      disabled={!canManage || busy || archived}
                      onChange={(event) => setCancelReason(event.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={
                      !canManage || busy || archived || !cancelReason.trim()
                    }
                    onClick={() =>
                      void mutate(
                        `/${draw.id}/cancel`,
                        { reason: cancelReason.trim() },
                        "Draw cancelled. It stays in history.",
                      )
                    }
                  >
                    Confirm cancellation
                  </button>
                </details>
              )}
              {draw.approved_at && (
                <BonusAnnouncement
                  key={draw.id}
                  draw={draw}
                  disabled={busy || archived}
                  onSend={(channel, retry = false) =>
                    void mutate(
                      `/${draw.id}/send`,
                      { channel_id: channel, retry },
                      "Delivery status updated below.",
                    )
                  }
                />
              )}
            </section>
          )}
          <details className="bonus-history">
            <summary>Saved bonus history ({data.history.length})</summary>
            <p className="small">
              Dashboard selections only; this is not proof medals were awarded
              in-game.
            </p>
            {data.draws
              .filter((item) => item.cancelled_at)
              .map((item) => (
                <div className="bonus-history-row" key={`cancelled-${item.id}`}>
                  <strong>{item.snapshot.clan_name} · Cancelled draw</strong>
                  <p>{item.cancel_reason}</p>
                  <small>{resultDateText(item.cancelled_at!)}</small>
                  <AccountList
                    accounts={item.snapshot.winners}
                    mode="winners"
                  />
                </div>
              ))}
            {data.history.map((item) => (
              <div className="bonus-history-row" key={item.id}>
                <strong>
                  {item.player_name} · {item.clan_name || item.clan_tag}
                </strong>
                <small>
                  {item.tag} · {exportMonthLabel(item.cycle)} ·{" "}
                  {item.voided_at ? "Voided" : "Approved"} ·{" "}
                  {resultDateText(item.confirmed_at)}
                </small>
              </div>
            ))}
          </details>
        </>
      )}
    </div>
  );
}
