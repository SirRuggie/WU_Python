import CwlPageHeader from "./CwlPageHeader";
import useDiscordIdentities from "./useDiscordIdentities";
import StrikeReviewResolution from "./StrikeReviewResolution";
import { parseActivityFilters } from "./strikeActivityFilters";
import StrikeActivityRoster from "./StrikeActivityRoster";
import {
  useViewState,
  useViewScroll,
  type ViewMemory,
} from "./strikeViewMemory";
import ManualStrikeEditor from "./ManualStrikeEditor";
import ConfirmDialog from "./ConfirmDialog";
import useUnsavedWork from "./useUnsavedWork";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { strikePermissions } from "./strikePermissions";
import StrikeTrackingStatus from "./StrikeTrackingStatus";
import StrikeHelp from "./StrikeHelp";
import { type StrikeStreakState } from "./StrikeStreak";
import { detailQuery } from "./strikeHistoryView";
import SectionTabs from "./SectionTabs";
import StrikesDetail from "./strikes/StrikesDetail";
import StrikesFindWar from "./strikes/StrikesFindWar";
import StrikesImportPanel from "./strikes/StrikesImportPanel";
import StrikesLeaveTab from "./strikes/StrikesLeaveTab";
import StrikesNotices from "./strikes/StrikesNotices";
import StrikesSettingsTab from "./strikes/StrikesSettingsTab";
import StrikesToolbar from "./strikes/StrikesToolbar";
import { errorText, savedImport, tabs } from "./strikes/format";
import type {
  ImportDraft,
  Overview,
  Settings,
  StrikeAccount,
  Tab,
  War,
} from "./strikes/types";
import { loadAccountDetail } from "./strikes/accountDetail";
import useLeaveApproval from "./strikes/useLeaveApproval";
import useStrikeImport from "./strikes/useStrikeImport";
import useWarSearch from "./strikes/useWarSearch";
import "./StrikesWorkspace.css";

export type { Entry } from "./strikes/types";
export default function StrikesWorkspace({
  permissions,
  isOwner,
  userId,
  onDirty,
  onFindReplacement,
  onMemberAccounts,
  targetTag = "",
  memory,
  onWorking,
  activityState,
  markedDefault = false,
  onActivityState,
  onAccountRoute,
}: {
  activityState?: string;
  markedDefault?: boolean;
  onActivityState?: (state: string, push: boolean) => void;
  onAccountRoute?: (tag: string) => void;
  permissions: string[];
  isOwner: boolean;
  userId: string;
  onDirty?: (dirty: boolean) => void;
  onWorking?: (busy: boolean) => void;
  onFindReplacement?: (clan: string, tag: string, weight?: number) => void;
  onMemberAccounts?: (memberId: string) => void;
  targetTag?: string;
  memory?: ViewMemory;
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
  const [trackingSlot, setTrackingSlot] = useState<HTMLDivElement | null>(null);
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
  const [activityReload, setActivityReload] = useState(0);
  const [selectedAccount, setSelectedAccount] =
    useViewState<StrikeAccount | null>(memory, "selectedAccount", null);
  const lastTarget = useRef(targetTag || selectedAccount?.player_tag || "");
  const [status, setStatus] = useViewState(memory, "status", "all");
  const [settingsDirty, setSettingsDirty] = useState(false);
  const activityClans = parseActivityFilters(
    activityState,
    markedDefault,
  ).clans;
  const clan = activityClans.length === 1 ? activityClans[0] : "";
  const {
    showWarSearch,
    setShowWarSearch,
    warSearchRef,
    warQuery,
    setWarQuery,
    wars,
    setWars,
    warPage,
    setWarPage,
    warTotal,
    warIncomplete,
    setWarRetry,
    warLoading,
    warError,
  } = useWarSearch({
    enabled: !accessLost && access.view && tab === "history",
    clan,
  });
  const [selectedWar, setSelectedWar] = useViewState<War | null>(
    memory,
    "selectedWar",
    null,
  );
  const [detailPage, setDetailPage] = useViewState(memory, "detailPage", 0);
  const page = detailPage;
  const setPage = setDetailPage;
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const listHeading = useRef<HTMLHeadingElement>(null);
  const returnPlayer = useRef<string | null>(null);
  const [loading, setLoading] = useState(false);
  useViewScroll(memory, !loading);
  const historyRequest = useRef(0);
  const [busy, setBusy] = useState(false);
  const [reviewDirty, setReviewDirty] = useState(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [replacementDirty, setReplacementDirty] = useState(false);
  const [replacementBusy, setReplacementBusy] = useState(false);
  useEffect(() => {
    onWorking?.(busy || replacementBusy || reviewBusy);
    return () => onWorking?.(false);
  }, [busy, replacementBusy, reviewBusy, onWorking]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const noticeRef = useRef<HTMLDivElement>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const {
    memberRequest,
    memberQuery,
    setMemberQuery,
    memberError,
    endingLeave,
    setEndingLeave,
    members,
    setMembers,
    selectedMember,
    setSelectedMember,
    leaveRevision,
    setLeaveRevision,
    leaveConflict,
    setLeaveConflict,
    resumeDate,
    setResumeDate,
    leaveTags,
    setLeaveTags,
    chooseMember,
  } = useLeaveApproval({
    accessLost,
    canView: access.view,
    tab,
    setError,
  });
  const [manualDirty, setManualDirty] = useState(false);
  const [bulkDirty, setBulkDirty] = useState(false);
  const [selectionReset, setSelectionReset] = useState(0);
  const mutation = useRef(false);
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
  const [removeId, setRemoveId] = useState("");
  const [removeReason, setRemoveReason] = useState("");
  const [settings, setSettings] = useState<Settings | null>(null);
  const {
    preview,
    setPreview,
    excluded,
    setExcluded,
    importJob,
    setImportJob,
    jobRetryPaused,
    startImportPreview,
    startImportApply,
    retryStatus,
  } = useStrikeImport({
    userId,
    initial: initialImport.current,
    mutation,
    setBusy,
    setError,
    setNotice,
    refreshHistory,
  });
  const discordProfiles = useDiscordIdentities(
    [
      selectedAccount?.discord_id,
      ...overview.entries.map((row) => row.discord_id),
      ...(settings?.leaves || []).map((row) => row.discord_id),
      ...members.map((row) => row.id),
      ...(preview?.entries || []).map((row) => row.discord_id),
    ],
    access.view && !accessLost,
    "/strikes/members",
  );
  useEffect(() => {
    if (discordProfiles.denied) setAccessLost(true);
  }, [discordProfiles.denied]);

  useEffect(() => {
    const clear = () => {
      historyRequest.current++;
      memberRequest.current++;
      setAccessLost(true);
      setOverview({ entries: [], clans: [], total: 0 });
      setSelectedAccount(null);
      setSelectedWar(null);
      setSettings(null);
      setMembers([]);
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
    reviewDirty ||
    replacementDirty ||
    settingsDirty ||
    manualDirty ||
    bulkDirty ||
    !!removeReason ||
    !!resumeDate ||
    leaveTags.length > 0;
  useUnsavedWork(dirty || busy, onDirty);
  const [pendingNavigation, setPendingNavigation] = useState<
    (() => void) | null
  >(null);
  const leaveDraft = (action: () => void) => {
    if (busy || replacementBusy || reviewBusy) return;
    if (dirty) setPendingNavigation(() => action);
    else action();
  };

  const openManual = () =>
    leaveDraft(() => {
      setNotice("");
      setError("");
      setManualOpen(true);
    });
  const refreshAccounts = useCallback(async () => {
    setActivityReload((value) => value + 1);
  }, []);
  useEffect(() => {
    if (
      accessLost ||
      !access.view ||
      tab !== "history" ||
      (!selectedAccount && !selectedWar)
    )
      return;
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
        setError("Changed by someone else · Refresh");
      } else setError(errorText(err));
    } finally {
      mutation.current = false;
      setBusy(false);
    }
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
      onAccountRoute?.("");
    });
  const chooseAccount = (account: StrikeAccount) => {
    setSelectedAccount(account);
    setSelectedWar(null);
    setStatus("all");
    setDetailPage(0);
  };
  useEffect(() => {
    const previous = lastTarget.current;
    lastTarget.current = targetTag;
    if (!targetTag) {
      if (previous) {
        returnPlayer.current = previous;
        setSelectedAccount(null);
        setSelectedWar(null);
      }
      return;
    }
    if (!access.view || accessLost || selectedAccount?.player_tag === targetTag)
      return;
    let active = true;
    void loadAccountDetail(targetTag)
      .then((found) => {
        if (!active) return;
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
    setShowWarSearch(false);
    setDetailPage(0);
  };
  const refreshAfterChange = async () => {
    if (selectedAccount || selectedWar) await refreshHistory();
    else await refreshAccounts();
    if (selectedAccount) {
      const updated = await loadAccountDetail(selectedAccount.player_tag);
      if (updated)
        setSelectedAccount((current) =>
          current?.player_tag === updated.player_tag ? updated : current,
        );
    }
  };
  const updateSettings = async () =>
    setSettings(await api<Settings>("/strikes/settings"));

  if (accessLost || !access.view)
    return (
      <p role="alert">
        Strike access changed. Reopen Strikes after your permissions refresh.
      </p>
    );

  return (
    <section
      className={`strikes-workspace${selectedAccount ? " strikes-player-detail" : !selectedWar ? " strikes-activity-overview" : ""}`}
    >
      <CwlPageHeader
        title={<h1>Strikes &amp; replacements</h1>}
        help={<StrikeHelp limit={settings?.strike_limit} />}
      />
      <div className="strikes-navigation">
        <SectionTabs
          className="strikes-tabs"
          label="Strike sections"
          items={visibleTabs}
          value={tab}
          disabled={busy}
          onChange={(nextTab) =>
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
              setTab(nextTab);
              setError("");
              setNotice("");
            })
          }
        />
        {tab === "history" && !manualOpen && (
          <StrikeTrackingStatus
            compact
            canRetry={access.add}
            portalTarget={trackingSlot}
          />
        )}
      </div>
      <StrikesNotices
        error={error}
        notice={notice}
        noticeRef={noticeRef}
        busy={busy}
        showLeaveRefresh={tab === "leave" && leaveConflict}
        onLeaveRefresh={() =>
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
        onRetry={
          tab === "history"
            ? () =>
                void (selectedAccount || selectedWar
                  ? refreshHistory()
                  : refreshAccounts())
            : (tab === "settings" || tab === "leave") &&
                access.manage &&
                !settings &&
                !leaveConflict
              ? () => {
                  setError("");
                  void updateSettings().catch((cause) =>
                    setError(errorText(cause)),
                  );
                }
              : undefined
        }
      />

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
          <StrikesToolbar
            canAdd={access.add}
            busy={busy}
            loading={loading}
            status={status}
            selectedAccount={selectedAccount}
            selectedWar={selectedWar}
            showWarSearch={showWarSearch}
            onBack={backToAccounts}
            onStatus={(value) =>
              leaveDraft(() => {
                setRemoveId("");
                setRemoveReason("");
                setStatus(value);
              })
            }
            onAdd={openManual}
            onToggleWarSearch={() => setShowWarSearch((open) => !open)}
            onRefresh={() => void refreshHistory()}
            onClearWar={() => leaveDraft(clearWar)}
          />
          {selectedWar?.manual_review_required && (
            <StrikeReviewResolution
              key={selectedWar.war_key}
              warKey={selectedWar.war_key}
              revision={selectedWar.review_revision || 0}
              reason={selectedWar.review_message}
              canManage={access.manage}
              onDirty={setReviewDirty}
              onWorking={setReviewBusy}
              onResolved={() => {
                setSelectedWar(null);
                setShowWarSearch(true);
                setWarRetry((value) => value + 1);
                setNotice("War review resolved. The streak hold is released.");
                requestAnimationFrame(() => noticeRef.current?.focus());
              }}
            />
          )}
          {!selectedAccount && showWarSearch && (
            <StrikesFindWar
              inputRef={warSearchRef}
              query={warQuery}
              onQuery={(value) => {
                setWarQuery(value);
                setWarPage(0);
              }}
              loading={warLoading}
              error={warError}
              wars={wars}
              incomplete={warIncomplete}
              total={warTotal}
              page={warPage}
              setPage={setWarPage}
              onChoose={(war) =>
                leaveDraft(() => {
                  setRemoveId("");
                  setRemoveReason("");
                  chooseWar(war);
                })
              }
              onRetry={() => setWarRetry((value) => value + 1)}
            />
          )}
          {selectedAccount || selectedWar ? (
            <StrikesDetail
              access={access}
              busy={busy}
              loading={loading}
              error={error}
              status={status}
              overview={overview}
              selectedAccount={selectedAccount}
              accountStreak={accountStreak}
              discordProfiles={discordProfiles}
              detailHeading={detailHeading}
              page={page}
              setPage={setPage}
              removeId={removeId}
              setRemoveId={setRemoveId}
              removeReason={removeReason}
              setRemoveReason={setRemoveReason}
              setReplacementDirty={setReplacementDirty}
              setReplacementBusy={setReplacementBusy}
              onFindReplacement={onFindReplacement}
              onMemberAccounts={onMemberAccounts}
              leaveDraft={leaveDraft}
              run={run}
              refreshAfterChange={refreshAfterChange}
            />
          ) : (
            <StrikeActivityRoster
              trackingSlotRef={setTrackingSlot}
              overviewActions={[
                ...(access.add
                  ? [
                      {
                        id: "add-strike",
                        label: "Add strike",
                        disabled: busy,
                        onAction: openManual,
                      },
                    ]
                  : []),
                {
                  id: "find-war",
                  label: showWarSearch ? "Close war search" : "Find war",
                  onAction: () => setShowWarSearch((open) => !open),
                },
              ]}
              selectionReset={selectionReset}
              canManage={access.manage}
              onWorking={setBusy}
              onDirty={setBulkDirty}
              state={activityState}
              markedDefault={markedDefault}
              reload={activityReload}
              memory={memory}
              headingRef={listHeading}
              focusTag={returnPlayer.current}
              onRestored={() => {
                returnPlayer.current = null;
              }}
              onState={onActivityState}
              onChoose={(account) => {
                leaveDraft(() => {
                  chooseAccount(account);
                  onAccountRoute?.(account.player_tag);
                });
              }}
              onDenied={() => setAccessLost(true)}
            />
          )}
        </>
      )}

      {tab === "leave" && access.manage && (
        <StrikesLeaveTab
          busy={busy}
          error={error}
          settings={settings}
          members={members}
          memberQuery={memberQuery}
          memberError={memberError}
          selectedMember={selectedMember}
          leaveTags={leaveTags}
          setLeaveTags={setLeaveTags}
          leaveConflict={leaveConflict}
          leaveRevision={leaveRevision}
          resumeDate={resumeDate}
          setResumeDate={setResumeDate}
          endingLeave={endingLeave}
          setEndingLeave={setEndingLeave}
          discordProfiles={discordProfiles}
          onMemberQuery={(value) => {
            memberRequest.current++;
            setMemberQuery(value);
            setSelectedMember("");
            setLeaveTags([]);
          }}
          chooseMember={chooseMember}
          run={run}
          updateSettings={updateSettings}
          onSaved={() => {
            setSelectedMember("");
            setMemberQuery("");
            setLeaveTags([]);
            setResumeDate("");
          }}
        />
      )}

      {tab === "settings" && access.manage && (
        <StrikesSettingsTab
          settings={settings}
          error={error}
          onSaved={setSettings}
          onDirty={setSettingsDirty}
          onBusy={setBusy}
        />
      )}

      {tab === "settings" && access.add && (
        <StrikesImportPanel
          open={importOpen}
          onToggle={setImportOpen}
          busy={busy}
          importJob={importJob}
          preview={preview}
          excluded={excluded}
          setExcluded={setExcluded}
          jobRetryPaused={jobRetryPaused}
          discordProfiles={discordProfiles}
          onPreview={() => void startImportPreview()}
          onApply={() => void startImportApply()}
          onRetryStatus={retryStatus}
        />
      )}
      {pendingNavigation && (
        <ConfirmDialog
          heading="Unsaved changes"
          text="Discard unsaved changes?"
          confirmLabel="Discard"
          cancelLabel="Keep editing"
          disabled={busy || reviewBusy}
          onCancel={() => setPendingNavigation(null)}
          onConfirm={() => {
            const action = pendingNavigation;
            setPendingNavigation(null);
            setSelectionReset((value) => value + 1);
            setBulkDirty(false);
            action();
          }}
        />
      )}
    </section>
  );
}
