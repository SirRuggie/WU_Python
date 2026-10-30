import StrikeReplacementRow from "./StrikeReplacementRow";
import {
  useViewState,
  useViewScroll,
  type ViewMemory,
} from "./strikeViewMemory";
import { strikeCountLabel } from "./strikeCountLabel";
import StrikeHistoryRow from "./StrikeHistoryRow";
import StrikeSettingsEditor, {
  type StrikeSettings,
} from "./StrikeSettingsEditor";
import ManualStrikeEditor from "./ManualStrikeEditor";
import ConfirmDialog from "./ConfirmDialog";
import useUnsavedWork from "./useUnsavedWork";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { strikePermissions } from "./strikePermissions";
import StrikeTrackingStatus from "./StrikeTrackingStatus";
import StrikeHelp from "./StrikeHelp";
import StrikeStreak, { type StrikeStreakState } from "./StrikeStreak";
import {
  detailQuery,
  importEmptyText,
  isCwlRecord,
  strikeLinkLabel,
  warMatchup,
  warSummary,
} from "./strikeHistoryView";
import {
  isStrikeImportJob,
  StrikeImportFailed,
  waitForStrikeImport,
  type StrikeImportJob,
} from "./strikeImportJobs";
import {
  defaultLeaveTags,
  selectedImportEntries,
  toggleLeaveTag,
} from "./strikeSelections";
import "./StrikesWorkspace.css";

type Tab = "history" | "leave" | "settings";
type Clan = { tag: string; name: string; is_fwa?: boolean };
type Account = { tag: string; name: string; current_clan_name?: string | null };
type Member = { id: string; name: string; accounts: Account[] };
export type Entry = {
  id: string;
  war_key?: string | null;
  opponent_name?: string | null;
  player_tag: string;
  player_name: string;
  discord_id?: string | null;
  discord_name?: string | null;
  link_status?: string | null;
  current_clan_name?: string | null;
  current_clan_tag?: string | null;
  war_clan_name?: string | null;
  war_clan_tag?: string | null;
  war_end?: string | null;
  expires_at?: string | null;
  exemption?: string | null;
  kind: "strike" | "miss" | "completed" | "cwl" | "no_attack";
  source: "war" | "manual" | "cwl";
  source_label?: string | null;
  war_type?: "regular" | "cwl";
  attacks_used?: number | null;
  attacks_per_member?: number | null;
  missed_attacks?: number | null;
  status:
    | "active"
    | "expired"
    | "removed"
    | "exempt"
    | "recorded"
    | "no_attack"
    | "completed";
  reason?: string | null;
  removed_reason?: string | null;
};
type Overview = {
  entries: Entry[];
  clans: Clan[];
  total: number;
  streak?: StrikeStreakState | null;
};
type StrikeAccount = {
  player_tag: string;
  player_name: string;
  discord_id?: string | null;
  link_status?: string | null;
  current_clan_tag?: string | null;
  current_clan_name?: string | null;
  clan_is_current?: boolean;
  active_strikes: number;
  total_strikes: number;
  over_limit?: boolean;
  new_this_week?: boolean;
  last_strike_at?: string | null;
};
type AccountOverview = {
  summary?: { over_limit: number; new_this_week: number };
  strike_limit?: number;
  accounts: StrikeAccount[];
  total: number;
  clans: Clan[];
};
type War = {
  war_key: string;
  clan_tag: string;
  clan_name: string;
  opponent_tag?: string;
  opponent_name: string;
  war_end: string;
  missed_accounts: number;
  strikes: number;
  one_missed: number;
  no_attack?: number | boolean;
  war_type?: "regular" | "cwl";
  cwl_missed?: number;
  source_label?: string | null;
  incomplete?: boolean;
  review_message?: string | null;
};
type Settings = StrikeSettings;
type ImportEntry = {
  key: string;
  player_tag: string;
  player_name: string;
  clan_name: string;
  war_end: string;
  missed_attacks: number;
  will_strike: boolean;
  kind?: string;
  source?: string;
  war_type?: "regular" | "cwl";
  attacks_used?: number | null;
  attacks_per_member?: number | null;
  discord_id?: string | null;
  link_status?: string | null;
  exempt?: boolean;
  duplicate?: boolean;
};
type DeferredAccount = {
  player_tag: string;
  player_name: string;
  clan_name: string;
  war_end?: string | null;
  missed_attacks?: number;
  reason?: string;
  link_status?: string | null;
};
type ImportResult = {
  added_strikes?: number;
  duplicates?: number;
  history_only?: number;
  excluded?: number;
  applied: number;
  strikes: number;
  skipped: number | unknown[];
  cwl_wars?: number;
  cwl_records?: number;
  cwl_missed?: number;
  deferred_count?: number;
  deferred_accounts?: DeferredAccount[];
};
type ActiveImportJob = { job_id: string; phase: "preview" | "apply" };
type ImportDraft = {
  job: ActiveImportJob | null;
  preview: ImportPreview | null;
  excluded: string[];
};
type ImportPreview = {
  preview_id: string;
  wars_scanned: number;
  complete_wars: number;
  incomplete_wars: number;
  cwl_wars?: number;
  cwl_records?: number;
  cwl_missed?: number;
  entries: ImportEntry[];
  deferred_accounts?: DeferredAccount[];
  deferred_count?: number;
  coverage: {
    clan_name: string;
    earliest?: string;
    latest?: string;
    wars: number;
    error?: string;
    skipped?: number;
    processing_skipped_wars?: number;
    deferred_accounts?: number;
  }[];
};

const tabs: { id: Tab; label: string }[] = [
  { id: "history", label: "Accounts" },
  { id: "leave", label: "Leave" },
  { id: "settings", label: "Settings" },
];
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Could not load data. Try again.";
const dateText = (value?: string | null) =>
  value
    ? /^\d{4}-\d{2}-\d{2}$/.test(value)
      ? new Date(`${value}T00:00:00`).toLocaleDateString()
      : new Date(value).toLocaleDateString()
    : "—";
const memberLabel = (member: Member) => `${member.name} · ${member.id}`;
const importStorageKey = (userId: string) => `wu:strikes:import:${userId}`;
function savedImport(userId: string): ImportDraft {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(importStorageKey(userId)) || "{}",
    );
    return {
      job:
        value.job &&
        typeof value.job.job_id === "string" &&
        ["preview", "apply"].includes(value.job.phase)
          ? value.job
          : null,
      preview:
        value.preview &&
        typeof value.preview.preview_id === "string" &&
        Array.isArray(value.preview.entries)
          ? value.preview
          : null,
      excluded: Array.isArray(value.excluded)
        ? value.excluded.filter((key: unknown) => typeof key === "string")
        : [],
    };
  } catch {
    return { job: null, preview: null, excluded: [] };
  }
}
const reviewCount = (count: number) =>
  `${count} ${count === 1 ? "needs" : "need"} review`;
const importResultText = (result: ImportResult) =>
  `${strikeCountLabel(result.added_strikes ?? result.strikes, "strike")} added · ${result.duplicates ?? (Array.isArray(result.skipped) ? result.skipped.length : result.skipped)} skipped as duplicate · ${result.history_only ?? result.applied - result.strikes} history-only${result.excluded ? ` · ${result.excluded} excluded` : ""}${(result.deferred_count ?? result.deferred_accounts?.length ?? 0) > 0 ? ` · ${reviewCount(result.deferred_count ?? result.deferred_accounts?.length ?? 0)}` : ""}.`;

export default function StrikesWorkspace({
  permissions,
  isOwner,
  userId,
  onDirty,
  onFindReplacement,
  targetTag = "",
  memory,
  onBack,
  onWorking,
}: {
  permissions: string[];
  isOwner: boolean;
  userId: string;
  onDirty?: (dirty: boolean) => void;
  onWorking?: (busy: boolean) => void;
  onFindReplacement?: (clan: string, tag: string) => void;
  targetTag?: string;
  memory?: ViewMemory;
  onBack?: () => void;
}) {
  const access = strikePermissions(permissions, isOwner);
  const visibleTabs = tabs.filter((item) =>
    item.id === "leave"
      ? access.manage
      : item.id === "settings"
        ? access.manage || access.add
        : true,
  );
  const initialImport = useRef<ImportDraft>(
    access.add
      ? savedImport(userId)
      : { job: null, preview: null, excluded: [] },
  );
  const [accessLost, setAccessLost] = useState(false);
  const [tab, setTab] = useState<Tab>(
    initialImport.current.job || initialImport.current.preview
      ? "settings"
      : "history",
  );
  const [importOpen, setImportOpen] = useState(
    !!(initialImport.current.job || initialImport.current.preview),
  );
  const [overview, setOverview] = useState<Overview>({
    entries: [],
    clans: [],
    total: 0,
  });
  const [accountStreak, setAccountStreak] = useState<{
    tag: string;
    streak?: StrikeStreakState | null;
  } | null>(null);
  const [accountOverview, setAccountOverview] = useState<AccountOverview>({
    accounts: [],
    clans: [],
    total: 0,
  });
  const [selectedAccount, setSelectedAccount] =
    useViewState<StrikeAccount | null>(memory, "selectedAccount", null);
  const [query, setQuery] = useViewState(memory, "query", "");
  const [historyMember, setHistoryMember] = useViewState<Member | null>(
    memory,
    "historyMember",
    null,
  );
  const [historyMatches, setHistoryMatches] = useState<Member[]>([]);
  const [status, setStatus] = useViewState(memory, "status", "all");
  const [actionFilter, setActionFilter] = useViewState(
    memory,
    "actionFilter",
    "all",
  );
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [accountStatus, setAccountStatus] = useViewState<"active" | "all">(
    memory,
    "accountStatus",
    "active",
  );
  const [showWarSearch, setShowWarSearch] = useState(false);
  const [warQuery, setWarQuery] = useState("");
  const [wars, setWars] = useState<War[]>([]);
  const [warPage, setWarPage] = useState(0);
  const [warTotal, setWarTotal] = useState(0);
  const [warIncomplete, setWarIncomplete] = useState(false);
  const [warRetry, setWarRetry] = useState(0);
  const [warLoading, setWarLoading] = useState(false);
  const [warError, setWarError] = useState("");
  const [selectedWar, setSelectedWar] = useViewState<War | null>(
    memory,
    "selectedWar",
    null,
  );
  const [clan, setClan] = useViewState(memory, "clan", "");
  const [accountPage, setAccountPage] = useViewState(memory, "accountPage", 0);
  const [detailPage, setDetailPage] = useViewState(memory, "detailPage", 0);
  const page = selectedAccount || selectedWar ? detailPage : accountPage;
  const setPage =
    selectedAccount || selectedWar ? setDetailPage : setAccountPage;
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const listHeading = useRef<HTMLHeadingElement>(null);
  const returnPlayer = useRef<string | null>(null);
  const [loading, setLoading] = useState(true);
  useViewScroll(memory, !loading);
  const historyRequest = useRef(0);
  const accountRequest = useRef(0);
  const memberRequest = useRef(0);
  const [busy, setBusy] = useState(false);
  const [replacementDirty, setReplacementDirty] = useState(false);
  const [replacementBusy, setReplacementBusy] = useState(false);
  useEffect(() => {
    onWorking?.(busy || replacementBusy);
    return () => onWorking?.(false);
  }, [busy, replacementBusy, onWorking]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [memberQuery, setMemberQuery] = useState("");
  const [memberError, setMemberError] = useState("");
  const [endingLeave, setEndingLeave] = useState("");
  const [members, setMembers] = useState<Member[]>([]);
  const [selectedMember, setSelectedMember] = useState("");
  const [manualDirty, setManualDirty] = useState(false);
  const mutation = useRef(false);
  const [removeId, setRemoveId] = useState("");
  const [removeReason, setRemoveReason] = useState("");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [leaveRevision, setLeaveRevision] = useState<number | null>(null);
  const [leaveConflict, setLeaveConflict] = useState(false);
  const [resumeDate, setResumeDate] = useState("");
  const [leaveTags, setLeaveTags] = useState<string[]>([]);
  const [preview, setPreview] = useState<ImportPreview | null>(
    initialImport.current.preview,
  );
  const [excluded, setExcluded] = useState<string[]>(
    initialImport.current.excluded,
  );
  const [importJob, setImportJob] = useState<ActiveImportJob | null>(
    initialImport.current.job,
  );
  const [jobRetryPaused, setJobRetryPaused] = useState(false);
  const [jobRetry, setJobRetry] = useState(0);

  useEffect(() => {
    const clear = () => {
      historyRequest.current++;
      accountRequest.current++;
      memberRequest.current++;
      setAccessLost(true);
      setOverview({ entries: [], clans: [], total: 0 });
      setAccountOverview({ accounts: [], clans: [], total: 0 });
      setSelectedAccount(null);
      setSelectedWar(null);
      setSettings(null);
      setMembers([]);
      setHistoryMatches([]);
      setWars([]);
      setManualOpen(false);
      setPreview(null);
      setImportJob(null);
      setPendingNavigation(null);
    };
    window.addEventListener("dashboard-access-changed", clear);
    return () => window.removeEventListener("dashboard-access-changed", clear);
  }, []);
  const dirty =
    replacementDirty ||
    settingsDirty ||
    manualDirty ||
    !!removeReason ||
    !!resumeDate ||
    leaveTags.length > 0;
  useUnsavedWork(dirty || busy, onDirty);
  const [pendingNavigation, setPendingNavigation] = useState<
    (() => void) | null
  >(null);
  const leaveDraft = (action: () => void) => {
    if (busy || replacementBusy) return;
    if (dirty) setPendingNavigation(() => action);
    else action();
  };

  const refreshHistory = useCallback(async () => {
    const request = ++historyRequest.current;
    setLoading(true);
    setError("");
    try {
      const params = detailQuery(
        page,
        status,
        selectedAccount?.player_tag,
        selectedWar?.war_key,
      );
      const data = await api<Overview>(`/strikes/overview?${params}`);
      if (request === historyRequest.current) {
        setOverview(data);
        setAccountStreak(
          selectedAccount
            ? { tag: selectedAccount.player_tag, streak: data.streak }
            : null,
        );
      }
    } catch (err) {
      if (request === historyRequest.current) setError(errorText(err));
    } finally {
      if (request === historyRequest.current) setLoading(false);
    }
  }, [page, status, selectedWar?.war_key, selectedAccount?.player_tag]);
  const refreshAccounts = useCallback(async () => {
    const request = ++accountRequest.current;
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        limit: "25",
        offset: String(page * 25),
        status: accountStatus,
        action: actionFilter,
      });
      if (historyMember?.id || query.trim())
        params.set("query", historyMember?.id || query.trim());
      if (clan) params.set("clan", clan);
      const data = await api<AccountOverview>(`/strikes/accounts?${params}`);
      if (request === accountRequest.current) setAccountOverview(data);
    } catch (err) {
      if (request === accountRequest.current) setError(errorText(err));
    } finally {
      if (request === accountRequest.current) setLoading(false);
    }
  }, [page, query, historyMember?.id, clan, accountStatus, actionFilter]);
  useEffect(() => {
    if (accessLost || !access.view || tab !== "history") return;
    const timer = setTimeout(
      () =>
        void (selectedAccount || selectedWar
          ? refreshHistory()
          : refreshAccounts()),
      180,
    );
    return () => {
      clearTimeout(timer);
      historyRequest.current++;
      accountRequest.current++;
    };
  }, [
    accessLost,
    access.view,
    tab,
    selectedAccount,
    selectedWar,
    refreshHistory,
    refreshAccounts,
  ]);
  useEffect(() => {
    if (
      accessLost ||
      !access.view ||
      !["history", "leave"].includes(tab) ||
      !memberQuery.trim()
    ) {
      setMembers([]);
      return;
    }
    let active = true;
    setMemberError("");
    const timer = setTimeout(() => {
      void api<{ members: Member[] }>(
        `/strikes/members?query=${encodeURIComponent(memberQuery.trim())}`,
      )
        .then((data) => {
          if (active) setMembers(data.members);
        })
        .catch((cause) => {
          if (active) {
            setMembers([]);
            setMemberError(errorText(cause));
          }
        });
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [accessLost, access.view, memberQuery, tab]);
  const accountFiltersMounted = useRef(false);
  useEffect(() => {
    if (!accountFiltersMounted.current) {
      accountFiltersMounted.current = true;
      return;
    }
    setAccountPage(0);
  }, [query, historyMember?.id, accountStatus, actionFilter, clan]);
  const detailFiltersMounted = useRef(false);
  useEffect(() => {
    if (!detailFiltersMounted.current) {
      detailFiltersMounted.current = true;
      return;
    }
    setDetailPage(0);
  }, [status]);
  useEffect(() => {
    detailHeading.current?.focus();
  }, [selectedAccount?.player_tag, selectedWar?.war_key]);
  useEffect(() => {
    if (selectedAccount || selectedWar || loading || !returnPlayer.current)
      return;
    const opener = document.querySelector<HTMLButtonElement>(
      `button[data-strike-player="${CSS.escape(returnPlayer.current)}"]`,
    );
    (opener || listHeading.current)?.focus();
    returnPlayer.current = null;
  }, [selectedAccount, selectedWar, loading]);
  useEffect(() => {
    if (accessLost || !access.view || tab !== "history" || !showWarSearch)
      return;
    let active = true;
    const timer = setTimeout(() => {
      setWarLoading(true);
      setWarError("");
      const params = new URLSearchParams({
        limit: "25",
        offset: String(warPage * 25),
      });
      if (warQuery.trim()) params.set("query", warQuery.trim());
      if (clan) params.set("clan", clan);
      void api<{
        wars: War[];
        total: number;
        name_search_incomplete?: boolean;
      }>(`/strikes/wars?${params}`)
        .then((data) => {
          if (active) {
            setWars(data.wars);
            setWarTotal(data.total);
            setWarIncomplete(!!data.name_search_incomplete);
          }
        })
        .catch((err) => {
          if (active) setWarError(errorText(err));
        })
        .finally(() => {
          if (active) setWarLoading(false);
        });
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [
    accessLost,
    access.view,
    tab,
    showWarSearch,
    warQuery,
    clan,
    warPage,
    warRetry,
  ]);
  useEffect(() => {
    if (
      accessLost ||
      !access.view ||
      tab !== "history" ||
      selectedAccount ||
      selectedWar ||
      historyMember ||
      query.trim().length < 2 ||
      query.trim().startsWith("#") ||
      /^\d+$/.test(query.trim())
    ) {
      setHistoryMatches([]);
      return;
    }
    let active = true;
    const timer = setTimeout(() => {
      void api<{ members: Member[] }>(
        `/strikes/members?query=${encodeURIComponent(query.trim())}`,
      )
        .then((data) => {
          if (active) setHistoryMatches(data.members);
        })
        .catch(() => {
          if (active) setHistoryMatches([]);
        });
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [
    accessLost,
    access.view,
    query,
    historyMember,
    tab,
    selectedAccount,
    selectedWar,
  ]);
  useEffect(() => {
    if (accessLost || !access.manage || (tab !== "settings" && tab !== "leave"))
      return;
    let active = true;
    setSettings(null);
    void api<Settings>("/strikes/settings")
      .then((data) => {
        if (active) setSettings(data);
      })
      .catch((err) => {
        if (active) setError(errorText(err));
      });
    return () => {
      active = false;
    };
  }, [accessLost, tab, access.manage]);
  const run = async (
    action: () => Promise<unknown>,
    success: string,
    after?: () => void | Promise<void>,
  ) => {
    if (mutation.current) return;
    mutation.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(success);
      await after?.();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setLeaveConflict(true);
        setError("Changed by someone else · Reload");
      } else setError(errorText(err));
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  };
  const chooseMember = async (id: string) => {
    const request = ++memberRequest.current;
    setLeaveTags([]);
    setLeaveRevision(null);
    setLeaveConflict(false);
    setSelectedMember(id);
    if (!id) {
      setLeaveTags([]);
      return;
    }
    let member: Member;
    try {
      member = (
        await api<{ member: Member }>(
          `/strikes/members/${encodeURIComponent(id)}/accounts`,
        )
      ).member;
      const state = await api<{ revision: number }>(
        `/strikes/settings/leaves/${encodeURIComponent(id)}`,
      );
      if (request !== memberRequest.current) return;
      setLeaveRevision(state.revision);
    } catch (err) {
      if (request === memberRequest.current) setError(errorText(err));
      return;
    }
    if (request !== memberRequest.current) return;
    setMembers((current) =>
      current.map((item) => (item.id === id ? member : item)),
    );
    setLeaveTags(defaultLeaveTags(member?.accounts || []));
  };
  const clearWar = () => {
    setSelectedWar(null);
    setStatus("all");
    setWarQuery("");
  };
  const backToAccounts = () =>
    leaveDraft(() => {
      returnPlayer.current = selectedAccount?.player_tag || null;
      setRemoveId("");
      setRemoveReason("");
      setSelectedAccount(null);
      clearWar();
    });
  const chooseAccount = (account: StrikeAccount) => {
    setSelectedAccount(account);
    setSelectedWar(null);
    setStatus("all");
    setDetailPage(0);
  };
  useEffect(() => {
    if (!targetTag || !access.view || accessLost) return;
    let active = true;
    void api<AccountOverview>(
      `/strikes/accounts?query=${encodeURIComponent(targetTag)}&status=all`,
    )
      .then((data) => {
        if (!active) return;
        const found = data.accounts.find(
          (account) => account.player_tag === targetTag,
        );
        if (found) {
          setTab("history");
          chooseAccount(found);
        } else setError("This account's strike history could not be found.");
      })
      .catch((cause) => {
        if (active) setError(errorText(cause));
      });
    return () => {
      active = false;
    };
  }, [targetTag, access.view, accessLost]);
  const chooseWar = (war: War) => {
    setSelectedAccount(null);
    setSelectedWar(war);
    setStatus("all");
    setQuery("");
    setHistoryMember(null);
    setShowWarSearch(false);
    setDetailPage(0);
  };
  const refreshAfterChange = async () => {
    if (selectedAccount || selectedWar) await refreshHistory();
    else await refreshAccounts();
    if (selectedAccount) {
      const data = await api<AccountOverview>(
        `/strikes/accounts?query=${encodeURIComponent(selectedAccount.player_tag)}&status=all`,
      );
      const updated = data.accounts.find(
        (account) => account.player_tag === selectedAccount.player_tag,
      );
      if (updated) setSelectedAccount(updated);
    }
  };
  const selected = members.find((item) => item.id === selectedMember);
  const importSelected = selectedImportEntries(
    preview?.entries || [],
    excluded,
  );
  const importStrikes = importSelected.filter(
    (item) => item.will_strike,
  ).length;
  const importAccounts = new Set(
    importSelected
      .filter((item) => item.will_strike)
      .map((item) => item.player_tag),
  ).size;
  const importHistory = importSelected.length - importStrikes;
  const deferredAccounts = preview?.deferred_accounts || [];
  const deferredCount = preview?.deferred_count ?? deferredAccounts.length;
  const updateSettings = async () =>
    setSettings(await api<Settings>("/strikes/settings"));
  useEffect(() => {
    try {
      if (!preview && !importJob)
        sessionStorage.removeItem(importStorageKey(userId));
      else
        sessionStorage.setItem(
          importStorageKey(userId),
          JSON.stringify({ preview, excluded, job: importJob }),
        );
    } catch {
      /* Browser storage is optional; active page still works. */
    }
  }, [userId, preview, excluded, importJob]);
  useEffect(() => {
    if (!importJob || jobRetryPaused) return;
    const controller = new AbortController();
    void waitForStrikeImport<ImportPreview | ImportResult>(
      importJob.job_id,
      (id) =>
        api<StrikeImportJob<ImportPreview | ImportResult>>(
          `/strikes/import/jobs/${encodeURIComponent(id)}`,
        ),
      controller.signal,
    )
      .then((result) => {
        if (controller.signal.aborted) return;
        if (importJob.phase === "preview") {
          setPreview(result as ImportPreview);
          setExcluded([]);
          setNotice("Preview ready.");
        } else {
          setPreview(null);
          setExcluded([]);
          setNotice(importResultText(result as ImportResult));
          void refreshHistory();
        }
        setImportJob(null);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (
          err instanceof StrikeImportFailed ||
          (err instanceof ApiError && err.status === 404)
        )
          setImportJob(null);
        else setJobRetryPaused(true);
        setError(errorText(err));
      });
    return () => controller.abort();
  }, [
    importJob?.job_id,
    importJob?.phase,
    refreshHistory,
    jobRetry,
    jobRetryPaused,
  ]);
  const startImportPreview = async () => {
    if (mutation.current) return;
    mutation.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<ImportPreview | StrikeImportJob<ImportPreview>>(
        "/strikes/import/preview",
        "POST",
        { days: 60 },
      );
      if (isStrikeImportJob(result)) {
        setJobRetryPaused(false);
        setImportJob({ job_id: result.job_id, phase: "preview" });
      } else {
        setPreview(result as ImportPreview);
        setExcluded([]);
        setNotice("Preview ready.");
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  };
  const startImportApply = async () => {
    if (!preview || mutation.current) return;
    mutation.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<ImportResult | StrikeImportJob<ImportResult>>(
        "/strikes/import/apply",
        "POST",
        { preview_id: preview.preview_id, excluded_keys: excluded },
      );
      if (isStrikeImportJob(result)) {
        setJobRetryPaused(false);
        setImportJob({ job_id: result.job_id, phase: "apply" });
      } else {
        setPreview(null);
        setExcluded([]);
        setNotice(importResultText(result as ImportResult));
        void refreshHistory();
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  };

  if (accessLost || !access.view)
    return (
      <p role="alert">
        Strike access changed. Reopen Strikes after your permissions refresh.
      </p>
    );

  return (
    <section
      className={`strikes-workspace${selectedAccount ? " strikes-player-detail" : ""}`}
    >
      {onBack && (
        <button type="button" disabled={busy} onClick={onBack}>
          ‹ Back to Replacements
        </button>
      )}
      <div className="page-head">
        <div>
          <p className="eyebrow">Family clans</p>
          <h1>Strikes</h1>
          <p>Review active strikes, account history, and approved leave.</p>
          {(settings?.strike_limit ?? accountOverview.strike_limit) != null && (
            <StrikeHelp
              limit={settings?.strike_limit ?? accountOverview.strike_limit}
            />
          )}
        </div>
      </div>
      <div className="strikes-tabs" role="group" aria-label="Strike sections">
        {visibleTabs.map((item) => (
          <button
            key={item.id}
            aria-pressed={tab === item.id}
            disabled={busy}
            onClick={() =>
              leaveDraft(() => {
                setManualOpen(false);
                setManualDirty(false);
                memberRequest.current++;
                setRemoveId("");
                setRemoveReason("");
                setLeaveTags([]);
                setLeaveRevision(null);
                setLeaveConflict(false);
                setResumeDate("");
                setTab(item.id);
                setError("");
                setNotice("");
              })
            }
          >
            {item.label}
          </button>
        ))}
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
          {tab === "leave" && leaveConflict && (
            <button
              disabled={busy}
              onClick={() =>
                leaveDraft(() => {
                  setResumeDate("");
                  setLeaveTags([]);
                  setEndingLeave("");
                  setLeaveConflict(false);
                  setError("");
                  void updateSettings().catch((cause) =>
                    setError(
                      cause instanceof Error
                        ? cause.message
                        : "Could not reload settings.",
                    ),
                  );
                  if (selectedMember) void chooseMember(selectedMember);
                })
              }
            >
              Reload
            </button>
          )}
          {tab === "history" && (
            <button
              disabled={busy}
              onClick={() =>
                void (selectedAccount || selectedWar
                  ? refreshHistory()
                  : refreshAccounts())
              }
            >
              Reload records
            </button>
          )}
        </div>
      )}
      {notice && (
        <div className="notice success" role="status">
          {notice}
        </div>
      )}

      {tab === "history" && manualOpen && (
        <ManualStrikeEditor
          initialAccount={selectedAccount}
          onDirty={setManualDirty}
          onBusy={setBusy}
          onCancel={() => {
            setManualOpen(false);
            setManualDirty(false);
            memberRequest.current++;
          }}
          onSaved={async () => {
            setManualOpen(false);
            setManualDirty(false);
            setNotice("Strike added.");
            await refreshAfterChange();
          }}
        />
      )}
      {tab === "history" && !manualOpen && (
        <>
          <StrikeTrackingStatus canRetry={access.add} />
          <div
            className={`strikes-toolbar${selectedAccount ? " strikes-toolbar-player" : ""}`}
          >
            {!selectedAccount && !selectedWar && (
              <div className="strikes-history-search">
                <label>
                  Find player or member
                  <input
                    type="search"
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value);
                      setHistoryMember(null);
                    }}
                    placeholder="Name, tag or Discord ID"
                  />
                </label>
                {historyMember && (
                  <button
                    className="strikes-picked-member"
                    onClick={() => {
                      setHistoryMember(null);
                      setQuery("");
                    }}
                  >
                    Member: {historyMember.name} ×
                  </button>
                )}
                {historyMatches.length > 0 && (
                  <div
                    className="strikes-search-matches"
                    role="group"
                    aria-label="Matching Discord members"
                  >
                    {historyMatches.map((item) => (
                      <button
                        key={item.id}
                        onClick={() => {
                          setHistoryMember(item);
                          setQuery(item.name);
                          setHistoryMatches([]);
                        }}
                      >
                        {item.name}
                        <small>{item.id}</small>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {selectedAccount && (
              <button onClick={backToAccounts}>← Players</button>
            )}
            {selectedAccount && (
              <label>
                Status
                <select
                  value={status}
                  disabled={!!selectedWar}
                  onChange={(event) => {
                    const value = event.target.value;
                    leaveDraft(() => {
                      setRemoveId("");
                      setRemoveReason("");
                      setStatus(value);
                    });
                  }}
                >
                  <option value="active">Active strikes</option>
                  <option value="expired">Expired strikes</option>
                  <option value="removed">Removed strikes</option>
                  <option value="recorded">
                    One attack missed (no strike)
                  </option>
                  <option value="cwl">CWL miss (no strike)</option>
                  <option value="exempt">Exempt (no strike)</option>
                  <option value="all">Everything</option>
                </select>
              </label>
            )}
            {!selectedAccount && !selectedWar && (
              <label>
                Show
                <select
                  value={accountStatus}
                  onChange={(event) =>
                    setAccountStatus(event.target.value as "active" | "all")
                  }
                >
                  <option value="active">Active strikes</option>
                  <option value="all">All accounts</option>
                </select>
              </label>
            )}
            {!selectedAccount && !selectedWar && (
              <label>
                Clan
                <select
                  value={clan}
                  onChange={(event) => {
                    setClan(event.target.value);
                    setWarPage(0);
                  }}
                >
                  <option value="">All clans</option>
                  {accountOverview.clans.map((item) => (
                    <option key={item.tag} value={item.tag}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {access.add && (
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  leaveDraft(() => {
                    setNotice("");
                    setError("");
                    setManualOpen(true);
                  })
                }
              >
                {manualOpen ? "Close" : "Add strike"}
              </button>
            )}
          </div>
          {!selectedAccount && (
            <div className="strikes-war-tools">
              <button
                disabled={busy || loading}
                onClick={() =>
                  void (selectedAccount || selectedWar
                    ? refreshHistory()
                    : refreshAccounts())
                }
              >
                Refresh records
              </button>
              <button
                aria-expanded={showWarSearch}
                onClick={() => setShowWarSearch((open) => !open)}
              >
                {showWarSearch ? "Close war search" : "Find war"}
              </button>
              {selectedWar && (
                <div className="strikes-selected-war">
                  <span>
                    {warMatchup(
                      selectedWar.clan_name,
                      selectedWar.opponent_name,
                    )}{" "}
                    · {dateText(selectedWar.war_end)} ·{" "}
                    {selectedWar.source_label || "Source unavailable"}
                    {selectedWar.no_attack
                      ? " · ⊖ No-attack war (no strike)"
                      : selectedWar.incomplete
                        ? " · Incomplete · No automatic strikes"
                        : " · All records"}
                  </span>
                  <button onClick={clearWar}>Clear war</button>
                </div>
              )}
            </div>
          )}
          {!selectedAccount && showWarSearch && (
            <div className="card strikes-war-search">
              <label>
                Find war
                <input
                  type="search"
                  value={warQuery}
                  onChange={(event) => {
                    setWarQuery(event.target.value);
                    setWarPage(0);
                  }}
                  placeholder="Opponent, clan, or date"
                />
              </label>
              {warLoading ? (
                <p role="status">Finding wars…</p>
              ) : warError ? (
                <p role="alert">
                  {warError}
                  <button onClick={() => setWarRetry((value) => value + 1)}>
                    Retry war search
                  </button>
                </p>
              ) : wars.length === 0 ? (
                <p>No saved wars found.</p>
              ) : (
                <div className="strikes-war-results">
                  {wars.map((war) => (
                    <button
                      key={war.war_key}
                      onClick={() =>
                        leaveDraft(() => {
                          setRemoveId("");
                          setRemoveReason("");
                          chooseWar(war);
                        })
                      }
                    >
                      <strong>
                        {warMatchup(war.clan_name, war.opponent_name)}
                      </strong>
                      <span>
                        {dateText(war.war_end)} ·{" "}
                        {war.source_label || "Source unavailable"} ·{" "}
                        {war.incomplete
                          ? `${war.review_message || "War ended before final check: review in Find war"} · No automatic strikes`
                          : warSummary(war)}
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {warIncomplete && (
                <p role="status">
                  Some opponent names are unavailable. Search by tag or date, or
                  retry.
                </p>
              )}
              {warTotal > 25 && (
                <div className="strikes-pages">
                  <button
                    disabled={warLoading || warPage === 0}
                    onClick={() => setWarPage((value) => value - 1)}
                  >
                    Previous wars
                  </button>
                  <span>
                    {warPage * 25 + 1}–{Math.min((warPage + 1) * 25, warTotal)}{" "}
                    of {warTotal}
                  </span>
                  <button
                    disabled={warLoading || (warPage + 1) * 25 >= warTotal}
                    onClick={() => setWarPage((value) => value + 1)}
                  >
                    Next wars
                  </button>
                </div>
              )}
            </div>
          )}
          {selectedAccount || selectedWar ? (
            <>
              {selectedAccount && (
                <div className="strikes-detail-context">
                  <h2 ref={detailHeading} tabIndex={-1}>
                    {selectedAccount.player_name}
                  </h2>
                  {selectedAccount.player_tag} ·{" "}
                  {strikeLinkLabel(
                    selectedAccount.discord_id,
                    null,
                    selectedAccount.link_status,
                  )}{" "}
                  ·{" "}
                  {selectedAccount.current_clan_name
                    ? `${selectedAccount.clan_is_current === false ? "Last known" : "Current"}: ${selectedAccount.current_clan_name}`
                    : "No clan"}{" "}
                  · {selectedAccount.active_strikes} active /{" "}
                  {strikeCountLabel(
                    selectedAccount.total_strikes,
                    "total strike",
                  )}
                  <StrikeReplacementRow
                    key={selectedAccount.player_tag}
                    tag={selectedAccount.player_tag}
                    canManage={access.manage}
                    onDirty={setReplacementDirty}
                    onWorking={setReplacementBusy}
                  />
                  <StrikeStreak
                    loading={loading}
                    streak={
                      !error &&
                      accountStreak?.tag === selectedAccount.player_tag
                        ? accountStreak.streak
                        : null
                    }
                  />
                </div>
              )}
              <div className="strikes-list-head">
                <h3>{selectedAccount ? "Strike history" : "War history"}</h3>
                <span>
                  {loading
                    ? "Loading…"
                    : strikeCountLabel(overview.total, "record")}
                </span>
              </div>
              {!loading && !error && overview.entries.length === 0 && (
                <div className="card strikes-empty">
                  {status === "strikes"
                    ? "No strikes found."
                    : "No records found."}
                </div>
              )}
              <div className="strikes-list">
                {!loading &&
                  !error &&
                  overview.entries.map((item) => (
                    <StrikeHistoryRow
                      key={item.id}
                      item={item}
                      showIdentity={!selectedAccount}
                      canRemove={
                        access.remove &&
                        item.kind === "strike" &&
                        item.status === "active"
                      }
                      removing={removeId === item.id}
                      onRemove={() =>
                        leaveDraft(() => {
                          setRemoveId(item.id);
                          setRemoveReason("");
                        })
                      }
                    >
                      <form
                        onSubmit={(event) => {
                          event.preventDefault();
                          if (!removeReason.trim()) return;
                          void run(
                            () =>
                              api(
                                `/strikes/${encodeURIComponent(item.id)}/remove`,
                                "POST",
                                { reason: removeReason.trim() },
                              ),
                            "Strike removed.",
                            async () => {
                              setRemoveId("");
                              setRemoveReason("");
                              await refreshAfterChange();
                            },
                          );
                        }}
                      >
                        <label>
                          Why remove?
                          <input
                            disabled={busy}
                            value={removeReason}
                            onChange={(event) =>
                              setRemoveReason(event.target.value)
                            }
                            required
                            maxLength={500}
                          />
                        </label>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            setRemoveId("");
                            setRemoveReason("");
                          }}
                        >
                          Cancel
                        </button>
                        <button disabled={busy || !removeReason.trim()}>
                          Confirm removal
                        </button>
                      </form>
                    </StrikeHistoryRow>
                  ))}
              </div>
              {overview.total > 25 && (
                <div className="strikes-pages">
                  <button
                    disabled={page === 0 || loading}
                    onClick={() =>
                      leaveDraft(() => {
                        setRemoveId("");
                        setRemoveReason("");
                        setPage((value) => value - 1);
                      })
                    }
                  >
                    Previous
                  </button>
                  <span>
                    {page * 25 + 1}–{Math.min((page + 1) * 25, overview.total)}{" "}
                    of {overview.total}
                  </span>
                  <button
                    disabled={(page + 1) * 25 >= overview.total || loading}
                    onClick={() =>
                      leaveDraft(() => {
                        setRemoveId("");
                        setRemoveReason("");
                        setPage((value) => value + 1);
                      })
                    }
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          ) : (
            <>
              {accountOverview.summary && !error && (
                <p className="strikes-action-summary" aria-live="polite">
                  {accountOverview.summary.over_limit} over limit ·{" "}
                  {accountOverview.summary.new_this_week} new this week
                  {loading ? " · Updating…" : ""}
                </p>
              )}
              <div
                className="strikes-action-chips"
                role="group"
                aria-label="Account action filters"
              >
                {(
                  [
                    ["over_limit", "Over limit"],
                    ["new_this_week", "New this week"],
                    ["all", "All"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    aria-pressed={actionFilter === value}
                    onClick={() => setActionFilter(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="strikes-list-head">
                <h2 ref={listHeading} tabIndex={-1}>
                  Players
                </h2>
                <span>
                  {loading
                    ? "Loading…"
                    : strikeCountLabel(accountOverview.total, "account")}
                </span>
              </div>
              {!loading && !error && accountOverview.accounts.length === 0 && (
                <div className="card strikes-empty">
                  {query || clan
                    ? "No accounts match these filters."
                    : accountStatus === "active"
                      ? "No active strikes. Choose All accounts to review past records."
                      : "No account history yet."}
                </div>
              )}
              <div className="strikes-account-list">
                {!loading &&
                  !error &&
                  accountOverview.accounts.map((account) => (
                    <div
                      className="strike-account-item"
                      key={account.player_tag}
                    >
                      <button
                        data-strike-player={account.player_tag}
                        className="card strikes-account-row"
                        key={account.player_tag}
                        onClick={() => chooseAccount(account)}
                      >
                        <span className="strikes-account-name">
                          <strong>
                            {account.player_name || account.player_tag}
                          </strong>
                          <small>
                            {account.player_tag} ·{" "}
                            {account.current_clan_name
                              ? `${account.clan_is_current === false ? "Last known" : "Current"}: ${account.current_clan_name}`
                              : "No clan"}
                          </small>
                          {!account.discord_id && <small>Not linked</small>}
                        </span>
                        <span className="strikes-account-count">
                          <strong>{account.active_strikes}</strong> active{" "}
                          {account.active_strikes === 1 ? "strike" : "strikes"}
                        </span>
                        <span className="strikes-account-more">
                          {account.total_strikes
                            ? `${account.total_strikes} total · Last ${dateText(account.last_strike_at)}`
                            : "Missed attacks only"}
                        </span>
                        <span aria-hidden="true">›</span>
                      </button>
                      {accountOverview.strike_limit != null &&
                        account.active_strikes >=
                          accountOverview.strike_limit && (
                          <div className="strike-account-action">
                            <span>
                              {account.active_strikes ===
                              accountOverview.strike_limit
                                ? "Limit reached"
                                : "Over limit"}{" "}
                              ({accountOverview.strike_limit})
                            </span>
                            {account.current_clan_tag && (
                              <a
                                href={`/clans/replacements?clan=${encodeURIComponent(account.current_clan_tag)}&tag=${encodeURIComponent(account.player_tag)}&from=strikes`}
                                onClick={(event) => {
                                  if (
                                    !onFindReplacement ||
                                    event.ctrlKey ||
                                    event.metaKey ||
                                    event.shiftKey ||
                                    event.altKey
                                  )
                                    return;
                                  event.preventDefault();
                                  onFindReplacement(
                                    account.current_clan_tag!,
                                    account.player_tag,
                                  );
                                }}
                              >
                                Find replacement ›
                              </a>
                            )}
                          </div>
                        )}
                    </div>
                  ))}
              </div>
              {accountOverview.total > 25 && (
                <div className="strikes-pages">
                  <button
                    disabled={page === 0 || loading}
                    onClick={() =>
                      leaveDraft(() => {
                        setRemoveId("");
                        setRemoveReason("");
                        setPage((value) => value - 1);
                      })
                    }
                  >
                    Previous
                  </button>
                  <span>
                    {page * 25 + 1}–
                    {Math.min((page + 1) * 25, accountOverview.total)} of{" "}
                    {accountOverview.total}
                  </span>
                  <button
                    disabled={
                      (page + 1) * 25 >= accountOverview.total || loading
                    }
                    onClick={() =>
                      leaveDraft(() => {
                        setRemoveId("");
                        setRemoveReason("");
                        setPage((value) => value + 1);
                      })
                    }
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}

      {tab === "leave" && access.manage && (
        <>
          <details className="card strikes-leave-editor">
            <summary>Approve leave</summary>
            <div className="strikes-form">
              <h2>Approve leave</h2>
              <label>
                Find Discord member
                <input
                  type="search"
                  disabled={busy}
                  value={memberQuery}
                  onChange={(event) => {
                    memberRequest.current++;
                    setMemberQuery(event.target.value);
                    setSelectedMember("");
                    setLeaveTags([]);
                  }}
                  placeholder="Name or Discord ID"
                />
              </label>
              {memberError && (
                <p className="notice error" role="alert">
                  {memberError} Try searching again.
                </p>
              )}
              {members.length > 0 && (
                <label>
                  Member
                  <select
                    disabled={busy}
                    value={selectedMember}
                    onChange={(event) => chooseMember(event.target.value)}
                  >
                    <option value="">Choose member</option>
                    {members.map((item) => (
                      <option key={item.id} value={item.id}>
                        {memberLabel(item)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {selected && (
                <div className="strikes-account-checks">
                  <span>Accounts on leave</span>
                  {selected.accounts.map((item) => (
                    <label key={item.tag}>
                      <input
                        type="checkbox"
                        disabled={busy}
                        checked={leaveTags.includes(item.tag)}
                        onChange={(event) =>
                          setLeaveTags((current) =>
                            toggleLeaveTag(
                              current,
                              item.tag,
                              event.target.checked,
                            ),
                          )
                        }
                      />
                      {item.name} · {item.tag}
                    </label>
                  ))}
                </div>
              )}
              <label>
                Resume on (UTC)
                <input
                  type="date"
                  disabled={busy}
                  value={resumeDate}
                  min={new Date().toISOString().slice(0, 10)}
                  onChange={(event) => setResumeDate(event.target.value)}
                />
              </label>
              <button
                className="primary"
                disabled={
                  busy ||
                  leaveConflict ||
                  leaveRevision === null ||
                  !selectedMember ||
                  !leaveTags.length ||
                  !resumeDate
                }
                onClick={() =>
                  void run(
                    () =>
                      api("/strikes/settings/leaves", "POST", {
                        discord_id: selectedMember,
                        player_tags: leaveTags,
                        resume_date: resumeDate,
                        revision: leaveRevision,
                      }),
                    "Leave saved.",
                    async () => {
                      await updateSettings();
                      setSelectedMember("");
                      setMemberQuery("");
                      setLeaveTags([]);
                      setResumeDate("");
                    },
                  )
                }
              >
                Save leave
              </button>
            </div>
          </details>
          {!settings && !error && <p role="status">Loading approved leave…</p>}
          <div className="strikes-list-head">
            <h2>Approved leave</h2>
          </div>
          {settings && settings.leaves.length === 0 && (
            <div className="card strikes-empty">No approved leave.</div>
          )}
          {settings?.leaves.map((item) => (
            <div className="card strikes-leave" key={item.discord_id}>
              <div>
                <strong>{item.display_name}</strong>
                <small>{item.player_tags.join(" · ")}</small>
                <span>Resume on: {dateText(item.resume_date)} UTC</span>
              </div>
              {endingLeave !== item.discord_id ? (
                <button
                  disabled={busy}
                  onClick={() => setEndingLeave(item.discord_id)}
                >
                  End leave
                </button>
              ) : (
                <div className="strikes-inline">
                  <span>End leave for {item.display_name} now?</span>
                  <button disabled={busy} onClick={() => setEndingLeave("")}>
                    Cancel
                  </button>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () =>
                          api(
                            `/strikes/settings/leaves/${encodeURIComponent(item.discord_id)}`,
                            "DELETE",
                            { revision: item.revision },
                          ),
                        "Leave ended.",
                        async () => {
                          setEndingLeave("");
                          await updateSettings();
                        },
                      )
                    }
                  >
                    Confirm end leave
                  </button>
                </div>
              )}
            </div>
          ))}
        </>
      )}

      {tab === "settings" &&
        access.manage &&
        (settings ? (
          <StrikeSettingsEditor
            settings={settings}
            onSaved={setSettings}
            onDirty={setSettingsDirty}
            onBusy={setBusy}
          />
        ) : (
          <p role="status">
            {error ? (
              <button
                onClick={() =>
                  void updateSettings().catch((cause) =>
                    setError(errorText(cause)),
                  )
                }
              >
                Retry settings
              </button>
            ) : (
              "Loading settings…"
            )}
          </p>
        ))}

      {tab === "settings" && access.add && (
        <details
          className="card strikes-import-settings"
          open={importOpen}
          onToggle={(event) => setImportOpen(event.currentTarget.open)}
        >
          <summary>
            Import past wars
            {importJob ? " · In progress" : preview ? " · Preview ready" : ""}
          </summary>
          <div className="strikes-import-content">
            <div className="strikes-form">
              <h2>Import recent wars</h2>
              <p>
                Check up to 60 days of wars. Regular war misses may add strikes;
                CWL is records only.
              </p>
              <button
                className="primary"
                disabled={busy || !!importJob}
                onClick={() => void startImportPreview()}
              >
                {busy || importJob?.phase === "preview"
                  ? "Checking wars…"
                  : preview
                    ? "Check again"
                    : "Check past wars"}
              </button>
            </div>
            {importJob && (
              <div className="strikes-job-status" role="status">
                <span>
                  {jobRetryPaused
                    ? "Connection paused. Retry status."
                    : importJob.phase === "preview"
                      ? "Checking wars… You can return later."
                      : "Importing records… You can return later."}
                </span>
                {jobRetryPaused && (
                  <button
                    onClick={() => {
                      setJobRetryPaused(false);
                      setError("");
                      setJobRetry((value) => value + 1);
                    }}
                  >
                    Retry status
                  </button>
                )}
              </div>
            )}
            {preview && (
              <>
                <p className="strikes-import-summary" aria-live="polite">
                  Adds {strikeCountLabel(importStrikes, "strike")} to{" "}
                  {strikeCountLabel(importAccounts, "account")} ·{" "}
                  {strikeCountLabel(importHistory, "history-only record")}
                </p>
                <p>
                  ClashKing (import) ·{" "}
                  {strikeCountLabel(preview.complete_wars, "complete war")} ·{" "}
                  {strikeCountLabel(preview.incomplete_wars, "skipped war")} ·{" "}
                  {reviewCount(deferredCount)}
                </p>
                <details className="card strikes-coverage">
                  <summary>Coverage by clan</summary>
                  {preview.coverage.map((item) => (
                    <div key={item.clan_name}>
                      <strong>{item.clan_name}</strong>
                      <span>
                        {item.error
                          ? "Unavailable"
                          : `${strikeCountLabel(item.wars, "war")}${item.skipped || item.processing_skipped_wars ? ` · ${strikeCountLabel((item.skipped || 0) + (item.processing_skipped_wars || 0), "skipped war")}` : ""}${item.deferred_accounts ? ` · ${reviewCount(item.deferred_accounts)}` : ""} · ${dateText(item.earliest)} to ${dateText(item.latest)}`}
                      </span>
                    </div>
                  ))}
                </details>
                <details className="strikes-import-review">
                  <summary>
                    Review selected records ({preview.entries.length})
                  </summary>
                  {preview.entries.length === 0 && (
                    <div className="card strikes-empty">
                      {importEmptyText(
                        preview.entries,
                        deferredCount,
                        preview.incomplete_wars,
                      )}
                    </div>
                  )}
                  <div className="strikes-list">
                    {preview.entries.map((item) => (
                      <div className="card strikes-import-row" key={item.key}>
                        <div>
                          <strong>{item.player_name}</strong>
                          <small>
                            {item.player_tag} · {item.clan_name} ·{" "}
                            {dateText(item.war_end)} ·{" "}
                            {strikeLinkLabel(
                              item.discord_id,
                              null,
                              item.link_status,
                            )}
                          </small>
                          <span>
                            {isCwlRecord(item)
                              ? `CWL · ${item.duplicate ? "Already recorded" : item.attacks_used === 0 || item.missed_attacks > 0 ? "Attack missed" : "Attack used"} · No strikes`
                              : `${item.missed_attacks} missed · ${item.duplicate ? "Already recorded" : item.exempt ? "Exempt" : item.will_strike ? "Strike" : "Record only"}`}
                          </span>
                        </div>
                        {!item.duplicate && (
                          <label className="strikes-check">
                            <input
                              type="checkbox"
                              checked={!excluded.includes(item.key)}
                              disabled={importJob?.phase === "apply"}
                              onChange={(event) =>
                                setExcluded((current) =>
                                  event.target.checked
                                    ? current.filter((key) => key !== item.key)
                                    : [...current, item.key],
                                )
                              }
                            />
                            {isCwlRecord(item)
                              ? "Save CWL record"
                              : item.exempt
                                ? "Save exempt record"
                                : item.will_strike
                                  ? "Add strike"
                                  : "Save record"}
                          </label>
                        )}
                      </div>
                    ))}
                  </div>
                </details>
                {deferredCount > 0 && (
                  <details className="card strikes-needs-review">
                    <summary>Needs review ({deferredCount})</summary>
                    <div className="strikes-review-list">
                      {deferredAccounts.map((item, index) => (
                        <div
                          key={`${item.player_tag}-${item.war_end || index}`}
                        >
                          <strong>{item.player_name || item.player_tag}</strong>
                          <small>
                            {item.player_tag} · {item.clan_name}
                            {item.war_end ? ` · ${dateText(item.war_end)}` : ""}
                          </small>
                          <span>
                            {item.missed_attacks != null
                              ? `${item.missed_attacks} missed · `
                              : ""}
                            {item.reason || "Account link needs review."}
                          </span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
                <div className="strikes-import-apply">
                  <span>
                    {strikeCountLabel(importSelected.length, "record")} selected
                  </span>
                  <button
                    className="primary"
                    disabled={
                      busy || !!importJob || importSelected.length === 0
                    }
                    onClick={() => void startImportApply()}
                  >
                    {busy || importJob?.phase === "apply"
                      ? "Importing…"
                      : `Add ${strikeCountLabel(importStrikes, "strike")}`}
                  </button>
                </div>
              </>
            )}
          </div>
        </details>
      )}
      {pendingNavigation && (
        <ConfirmDialog
          heading="Unsaved changes"
          text="Discard unsaved changes?"
          confirmLabel="Discard"
          cancelLabel="Keep editing"
          disabled={busy}
          onCancel={() => setPendingNavigation(null)}
          onConfirm={() => {
            const action = pendingNavigation;
            setPendingNavigation(null);
            action();
          }}
        />
      )}
    </section>
  );
}
