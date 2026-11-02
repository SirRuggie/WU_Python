import AnnouncementDeletedRecovery from "./AnnouncementDeletedRecovery";
import AnnouncementFullTest from "./AnnouncementFullTest";
import AnnouncementSequenceStatus from "./AnnouncementSequenceStatus";
import { announcementPoolLabel as poolLabel } from "./announcementPoolLabel";
import AnnouncementPoolCard from "./AnnouncementPoolCard";
import AnnouncementEditor from "./AnnouncementEditor";
import { Button } from "./rosterUi/primitives";
import { RefreshCw, Send } from "lucide-react";
import AnnouncementMonth from "./AnnouncementMonth";
import { announcementMonth } from "./announcementMonth";
import ConfirmDialog from "./ConfirmDialog";
import "./announcementWorkspace.css";
import AnnouncementSendReview from "./AnnouncementSendReview";
import { useReminderLookup } from "./useReminderLookups";
import {
  announcementDeliveryStatus,
  announcementPublicationStatus,
} from "./announcementDelivery";
import type { PublicationDraft } from "./publication";
import { useDashboardPermission } from "./DashboardPermissions";
import {
  reconcileAnnouncementSave,
  type AnnouncementDraft,
} from "./announcementDrafts";
import AnnouncementPreviewDialog from "./AnnouncementPreviewDialog";
import DiscordPreview, { type PreviewPart } from "./DiscordMessagePreview";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Pool } from "./api";
import { type AnnouncementChannel } from "./announcements";
import {
  canQueueAnnouncement,
  dashboardRosterUrl,
  isSecureOrigin,
  normalizeManageBridge,
  shouldPollBridge,
  type ManageBridge,
} from "./manageBridge";

type Props = {
  publication?: Pick<PublicationDraft, "published" | "last_publication">;
  onFinalize?: () => void;
  seasonLabel?: string;
  onDeclaration?: () => void;
  seasonId: string;
  publicationVersion: number | null;
  onDirty?: (dirty: boolean) => void;
  onBusy?: (busy: boolean) => void;
};
type PoolDraft = AnnouncementDraft;
type Notice = { kind: "success" | "error"; text: string } | null;
const pools: Pool[] = ["main", "lazy"];
const emptyDraft = (): Record<Pool, PoolDraft> => ({
  main: { channel_id: "", body: "", roster_url: "" },
  lazy: { channel_id: "", body: "", roster_url: "" },
});
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Manage CWL settings request failed. Try again.";
const draftFrom = (bridge: ManageBridge): Record<Pool, PoolDraft> => ({
  main: {
    channel_id: bridge.pools.main.channel_id || "",
    body: bridge.pools.main.body || "",
    roster_url: bridge.pools.main.roster_url || "",
  },
  lazy: {
    channel_id: bridge.pools.lazy.channel_id || "",
    body: bridge.pools.lazy.body || "",
    roster_url: bridge.pools.lazy.roster_url || "",
  },
});
const safeMessageUrl = (url: string | null | undefined) =>
  !!url && /^https:\/\/(discord\.com|ptb\.discord\.com)\/channels\//.test(url);

export default function ManageBridgeWorkspace({
  seasonId,
  seasonLabel = "",
  publication,
  onFinalize,
  publicationVersion,
  onDirty,
  onBusy,
  onDeclaration,
}: Props) {
  const canManage = useDashboardPermission("cwl_send");
  const canDeclare = useDashboardPermission("cwl_roster");
  const [confirmation, setConfirmation] = useState<"refresh" | Pool | null>(
    null,
  );
  const [confirmMonth, setConfirmMonth] = useState(false);
  const [deletedPools, setDeletedPools] = useState<Pool[]>([]);
  const [resultPools, setResultPools] = useState<Pool[]>([]);
  const [sendReview, setSendReview] = useState<Pool[] | null>(null);
  const roles = useReminderLookup<{ id: string; name: string }>(
    "/announcement-roles",
    "roles",
  );
  const sending = useRef(false);
  const [bridge, setBridge] = useState<ManageBridge | null>(null);
  const [expandedPreview, setExpandedPreview] = useState<Pool | null>(null);
  const [editor, setEditor] = useState<{
    pool: Pool;
    trigger: HTMLElement;
  } | null>(null);
  const [testChannel, setTestChannel] = useState("");
  const [testUrl, setTestUrl] = useState("");
  const [channels, setChannels] = useState<AnnouncementChannel[]>([]);
  const [drafts, setDrafts] = useState<Record<Pool, PoolDraft>>(emptyDraft);
  const [draftGeneration, setDraftGeneration] = useState<string | null>(null);
  const [cycleInput, setCycleInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [bridgeError, setBridgeError] = useState("");
  const [channelsError, setChannelsError] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const requestId = useRef(0);
  const latestBridge = useRef(bridge);
  latestBridge.current = bridge;
  const latestDrafts = useRef(drafts);
  latestDrafts.current = drafts;
  const activeSeason = useRef(seasonId);
  activeSeason.current = seasonId;
  const load = useCallback(
    async (resetDraft: boolean | Pool = false) => {
      if (!seasonId) return;
      const sid = seasonId;
      const id = ++requestId.current;
      setLoading(true);
      setBridgeError("");
      try {
        const result = normalizeManageBridge(
          await api<ManageBridge>(
            `/seasons/${encodeURIComponent(sid)}/manage-bridge`,
          ),
        );
        if (id !== requestId.current || activeSeason.current !== sid) return;
        setBridge(result);
        const initialize = resetDraft === true || latestBridge.current === null;
        if (resetDraft || initialize) {
          const saved = draftFrom(result);
          const reconciliation =
            initialize || typeof resetDraft !== "string"
              ? null
              : reconcileAnnouncementSave(
                  resetDraft,
                  latestDrafts.current,
                  latestBridge.current ? draftFrom(latestBridge.current) : null,
                  saved,
                );
          setDrafts(reconciliation?.drafts || saved);
          if (!reconciliation?.conflict) setDraftGeneration(result.generation);
          if (initialize)
            setCycleInput(result.cycle || announcementMonth(seasonLabel));
        }
      } catch (error) {
        if (id === requestId.current && activeSeason.current === sid) {
          setBridgeError(errorText(error));
          if (error instanceof ApiError && [401, 403].includes(error.status)) {
            setBridge(null);
            setDrafts(emptyDraft());
            setDraftGeneration(null);
          }
        }
      } finally {
        if (id === requestId.current && activeSeason.current === sid)
          setLoading(false);
      }
    },
    [seasonId, seasonLabel],
  );
  const loadChannels = useCallback(async () => {
    try {
      setChannels(
        (
          await api<{ channels: AnnouncementChannel[] }>(
            "/announcement-channels",
          )
        ).channels,
      );
      setChannelsError("");
    } catch (error) {
      setChannels([]);
      setChannelsError(errorText(error));
    }
  }, []);
  useEffect(() => {
    requestId.current += 1;
    activeSeason.current = seasonId;
    setResultPools([]);
    setDeletedPools([]);
    setSendReview(null);
    setExpandedPreview(null);
    setEditor(null);
    setConfirmMonth(false);
    setConfirmation(null);
    setTestUrl("");
    setBridge(null);
    setDrafts(emptyDraft());
    setDraftGeneration(null);
    setCycleInput("");
    setNotice(null);
    setBridgeError("");
    setChannelsError("");
    if (seasonId) {
      void load(true);
      void loadChannels();
    }
    return () => {
      requestId.current++;
      activeSeason.current = "";
    };
  }, [seasonId, load, loadChannels]);
  const observedPublication = useRef(publicationVersion);
  useEffect(() => {
    if (observedPublication.current === publicationVersion) return;
    const previousVersion = observedPublication.current;
    observedPublication.current = publicationVersion;
    // Publication refreshes must not replace unsaved message drafts.
    setSendReview(null);
    if (previousVersion !== null)
      setNotice({
        kind: "error",
        text: "The published roster changed. Review the new version before sending; your message edits are retained.",
      });
    void load(false);
  }, [publicationVersion, load]);
  useEffect(() => {
    if (
      !seasonId ||
      busy ||
      sendReview ||
      loading ||
      bridgeError ||
      !shouldPollBridge(bridge)
    )
      return;
    const timer = window.setTimeout(() => void load(false), 5000);
    return () => window.clearTimeout(timer);
  }, [seasonId, bridge, load, busy, sendReview, loading, bridgeError]);
  const setDraft = (pool: Pool, update: Partial<PoolDraft>) =>
    setDrafts((current) => ({
      ...current,
      [pool]: { ...current[pool], ...update },
    }));
  const unsaved = (pool: Pool) => {
    if (!bridge) return false;
    const saved = draftFrom(bridge)[pool];
    const current = drafts[pool];
    return (
      saved.channel_id !== current.channel_id ||
      saved.body !== current.body ||
      saved.roster_url !== current.roster_url
    );
  };
  const dirty =
    !!bridge &&
    (pools.some(unsaved) ||
      cycleInput !== (bridge.cycle || announcementMonth(seasonLabel)));
  useEffect(() => {
    onBusy?.(busy || !!sendReview || !!confirmation || confirmMonth);
    return () => onBusy?.(false);
  }, [busy, sendReview, confirmation, confirmMonth, onBusy]);
  useEffect(() => {
    onDirty?.(dirty);
    return () => onDirty?.(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const refresh = () => {
    setConfirmation(null);
    setNotice(null);
    void load(true);
    void loadChannels();
  };
  const reviewRefresh = () => {
    if (dirty) setConfirmation("refresh");
    else refresh();
  };
  const bindCycle = async () => {
    if (
      !canManage ||
      !seasonId ||
      busy ||
      loading ||
      !!bridgeError ||
      !/^\d{4}-(0[1-9]|1[0-2])$/.test(cycleInput)
    ) {
      setNotice({
        kind: "error",
        text: "Choose a CWL month in YYYY-MM format.",
      });
      return;
    }
    setConfirmMonth(false);
    const sid = seasonId;
    setBusy(true);
    setNotice(null);
    try {
      await api(
        `/seasons/${encodeURIComponent(sid)}/manage-bridge/bind`,
        "POST",
        { cycle: cycleInput },
      );
      if (activeSeason.current === sid) {
        await load(true);
        setNotice({
          kind: "success",
          text: `Season bound to Manage CWL settings ${cycleInput}. Review both messages before sending.`,
        });
      }
    } catch (error) {
      if (activeSeason.current === sid)
        setNotice({ kind: "error", text: errorText(error) });
    } finally {
      setBusy(false);
    }
  };
  const save = async (pool: Pool) => {
    if (
      !canManage ||
      loading ||
      bridgeError ||
      !bridge?.generation ||
      !seasonId ||
      busy ||
      draftGeneration !== bridge.generation ||
      !unsaved(pool)
    )
      return;
    const source = drafts[pool];
    if (
      !/^\d{15,22}$/.test(source.channel_id) ||
      !channels.some((channel) => channel.id === source.channel_id)
    ) {
      setNotice({
        kind: "error",
        text: "Choose a current Discord guild channel.",
      });
      return;
    }
    if (
      source.channel_id === drafts[pool === "main" ? "lazy" : "main"].channel_id
    ) {
      setNotice({
        kind: "error",
        text: "Main and Lazy announcements need different channels.",
      });
      return;
    }
    if (!/^https:\/\/[^\s]+$/.test(source.roster_url)) {
      setNotice({
        kind: "error",
        text: "Enter an HTTPS roster button URL before saving.",
      });
      return;
    }
    const sid = seasonId;
    setBusy(true);
    setNotice(null);
    try {
      await api(
        `/seasons/${encodeURIComponent(sid)}/manage-bridge/${pool}`,
        "PATCH",
        {
          generation: bridge.generation,
          channel_id: source.channel_id,
          body: source.body,
          roster_url: source.roster_url,
        },
      );
      if (activeSeason.current === sid) {
        await load(pool);
        setNotice({
          kind: "success",
          text: `${poolLabel(pool)} Manage message saved. No announcement was sent.`,
        });
      }
    } catch (error) {
      if (activeSeason.current === sid)
        setNotice({
          kind: "error",
          text:
            error instanceof ApiError && error.status === 409
              ? `${error.message} Manage settings changed. Copy any unsaved text, then refresh and review before retrying.`
              : errorText(error),
        });
    } finally {
      setBusy(false);
    }
  };
  const sendTest = async (pool: Pool) => {
    if (
      !canManage ||
      !bridge ||
      busy ||
      loading ||
      bridgeError ||
      channelsError ||
      draftGeneration !== bridge.generation ||
      sending.current ||
      !channels.some((channel) => channel.id === testChannel)
    ) {
      setConfirmation(null);
      setNotice({
        kind: "error",
        text: "Test not sent: permissions, settings or channel availability changed. Refresh status and review before trying again.",
      });
      return;
    }
    sending.current = true;
    setConfirmation(null);
    const sid = seasonId;
    setBusy(true);
    setNotice(null);
    setTestUrl("");
    try {
      const nonce = Array.from(
        crypto.getRandomValues(new Uint8Array(12)),
        (byte) => byte.toString(16).padStart(2, "0"),
      ).join("");
      const result = await api<{ url: string }>(
        `/seasons/${encodeURIComponent(sid)}/manage-bridge/${pool}/test`,
        "POST",
        {
          channel_id: testChannel,
          request_id: nonce,
          generation: bridge.generation,
          body: drafts[pool].body,
          roster_url: drafts[pool].roster_url,
        },
      );
      if (activeSeason.current === sid) {
        setTestUrl(result.url);
        setNotice({
          kind: "success",
          text: "Test sent. The real announcement is unchanged.",
        });
      }
    } catch (error) {
      if (activeSeason.current === sid)
        setNotice({ kind: "error", text: errorText(error) });
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };
  const readyPools = pools.filter(
    (pool) =>
      canManage &&
      !bridgeError &&
      !!bridge &&
      !busy &&
      !loading &&
      !channelsError &&
      draftGeneration === bridge.generation &&
      channels.some((channel) => channel.id === drafts[pool].channel_id) &&
      canQueueAnnouncement(
        bridge,
        pool,
        drafts[pool].channel_id,
        unsaved(pool),
      ),
  );
  const sendBoth = async (selected: Pool[]) => {
    if (
      !bridge ||
      !selected.length ||
      !selected.every((pool) => readyPools.includes(pool)) ||
      sending.current
    )
      return;
    sending.current = true;
    setSendReview(null);
    const sid = seasonId;
    setBusy(true);
    setNotice(null);
    const results: string[] = [];
    const queued: Pool[] = [];
    for (const pool of selected) {
      try {
        await api(
          `/seasons/${encodeURIComponent(sid)}/manage-bridge/${pool}/send`,
          "POST",
          {
            generation: bridge.generation,
            channel_id: drafts[pool].channel_id,
            version: bridge.published_version,
          },
        );
        results.push(`${poolLabel(pool)} queued.`);
        queued.push(pool);
      } catch (error) {
        results.push(`${poolLabel(pool)}: ${errorText(error)}`);
      }
    }
    if (activeSeason.current === sid) {
      setNotice({
        kind: results.every((result) => result.endsWith(" queued."))
          ? "success"
          : "error",
        text: results.join(" "),
      });
      await load(false);
      setResultPools(queued);
    }
    sending.current = false;
    setBusy(false);
  };
  const preview = (pool: Pool) =>
    bridge ? (
      <DiscordPreview
        parts={[
          {
            type: "container",
            children: [
              {
                type: "text",
                text: "## " + (bridge.pools[pool].title || "Untitled"),
              },
              { type: "text", text: drafts[pool].body },
              ...(bridge.pools[pool].role_ids.length
                ? [
                    {
                      type: "text",
                      text: bridge.pools[pool].role_ids
                        .map((id) => `<@&${id}>`)
                        .join(" "),
                    } as PreviewPart,
                  ]
                : []),
              ...(bridge.pools[pool].media_url
                ? [
                    {
                      type: "media",
                      items: [
                        {
                          url: bridge.pools[pool].media_url,
                          description: "Roster announcement image",
                        },
                      ],
                    } as PreviewPart,
                  ]
                : []),
              {
                type: "row",
                children: bridge.pools[pool].buttons.map((button, index) => ({
                  type: "button",
                  label: button.label,
                  emoji: button.emoji,
                  url:
                    index === 0 && drafts[pool].roster_url
                      ? drafts[pool].roster_url
                      : button.url,
                })),
              },
            ],
          },
        ]}
      />
    ) : null;
  return (
    <section
      className="manage-bridge-workspace announcement-workspace"
      aria-label="Announcements"
    >
      <p className="announcement-muted">
        Sending posts to Discord and pings the listed roles. Publishing doesn't
        send anything.
      </p>
      <header className="announcement-toolbar">
        <span>
          {announcementPublicationStatus(publication)}
          {publication && !publication.published && onFinalize && (
            <>
              {" · "}
              <Button
                disabled={busy || dirty || !!sendReview}
                onClick={onFinalize}
              >
                Finalize roster ›
              </Button>
            </>
          )}
        </span>
        <Button
          icon={RefreshCw}
          disabled={busy || loading}
          onClick={reviewRefresh}
        >
          Refresh status
        </Button>
      </header>
      {notice && (
        <div
          className={`notice ${notice.kind}`}
          role={notice.kind === "error" ? "alert" : "status"}
        >
          {notice.text}
        </div>
      )}
      {bridgeError && (
        <div className="notice error" role="alert">
          {bridgeError}
        </div>
      )}
      {channelsError && (
        <div className="notice error" role="alert">
          <span>Discord channels are unavailable. Sending is disabled.</span>
          <button disabled={busy} onClick={() => void loadChannels()}>
            Retry channels
          </button>
        </div>
      )}
      {loading && (
        <div role="status">
          <p>Checking announcement settings…</p>
          <p className="announcement-muted">This can take up to 20 seconds.</p>
        </div>
      )}
      {bridge && (
        <>
          <AnnouncementMonth
            key={`${seasonId}:${bridge.cycle}`}
            value={cycleInput}
            linked={bridge.cycle}
            disabled={!canManage || busy || loading || !!bridgeError}
            onChange={setCycleInput}
            onLoad={() => {
              if (bridge.cycle || pools.some(unsaved)) setConfirmMonth(true);
              else void bindCycle();
            }}
          />
          {bridge.cycle && !bridge.worker_ready && (
            <p className="notice error" role="alert">
              The bot is restarting or offline. Refresh status in a minute.
            </p>
          )}
          {bridge.cycle && (
            <>
              <div className="announcement-pool-cards">
                {pools.map((pool) => {
                  const entry = bridge.pools[pool],
                    delivery = entry.delivery;
                  const locked =
                    !!delivery &&
                    ["sent", "pending", "sending", "uncertain"].includes(
                      delivery.status,
                    );
                  return (
                    <AnnouncementPoolCard
                      key={pool}
                      pool={pool}
                      sequence={
                        <>
                          <AnnouncementSequenceStatus
                            key={`${seasonId}:${pool}`}
                            seasonId={seasonId}
                            pool={pool}
                            sequence={entry.sequence}
                            resultOpen={!bridgeError && resultPools[0] === pool}
                            onResultClose={() =>
                              setResultPools((items) =>
                                items.filter((item) => item !== pool),
                              )
                            }
                            messageUrl={
                              entry.sequence?.message_url ||
                              delivery?.message_url
                            }
                            announcementSent={delivery?.status === "sent"}
                            channelName={
                              channels.find(
                                (channel) =>
                                  channel.id === entry.sequence?.channel_id,
                              )?.name
                                ? `#${channels.find((channel) => channel.id === entry.sequence?.channel_id)!.name}`
                                : "the reviewed channel"
                            }
                            canSend={canManage && !busy}
                            onRefresh={() => load(false)}
                          />
                          {delivery?.status === "sent" && (
                            <AnnouncementDeletedRecovery
                              key={`recovery:${seasonId}:${pool}`}
                              seasonId={seasonId}
                              pool={pool}
                              cycle={bridge.cycle || ""}
                              version={bridge.published_version}
                              generation={bridge.generation || ""}
                              channel={drafts[pool].channel_id}
                              channelName={
                                channels.find(
                                  (channel) =>
                                    channel.id === drafts[pool].channel_id,
                                )?.name || drafts[pool].channel_id
                              }
                              roleNames={entry.role_ids.map(
                                (id) =>
                                  roles.items.find((role) => role.id === id)
                                    ?.name || `Role ${id}`,
                              )}
                              clans={
                                entry.sequence?.published_clans?.map(
                                  (clan) => ({
                                    ...clan,
                                    status: "not_started",
                                  }),
                                ) || []
                              }
                              preview={preview(pool)}
                              allowed={
                                canManage &&
                                !busy &&
                                !loading &&
                                !bridgeError &&
                                !channelsError &&
                                !unsaved(pool) &&
                                draftGeneration === bridge.generation
                              }
                              onDeleted={(deleted) =>
                                setDeletedPools((items) =>
                                  deleted
                                    ? [...new Set([...items, pool])]
                                    : items.filter((item) => item !== pool),
                                )
                              }
                              onQueued={() =>
                                void load(false).then(() =>
                                  setResultPools([pool]),
                                )
                              }
                            />
                          )}
                        </>
                      }
                      tests={
                        <AnnouncementFullTest
                          key={`${seasonId}:${pool}`}
                          seasonId={seasonId}
                          pool={pool}
                          version={bridge.published_version}
                          generation={bridge.generation || ""}
                          draft={drafts[pool]}
                          channels={channels}
                          allowed={
                            canManage &&
                            !busy &&
                            !loading &&
                            !bridgeError &&
                            !channelsError &&
                            draftGeneration === bridge.generation
                          }
                          clanNames={(
                            entry.sequence?.published_clans || []
                          ).map((clan) => clan.name)}
                        />
                      }
                      enabled={entry.enabled}
                      changed={unsaved(pool)}
                      editable={canManage}
                      channel={
                        channels.find(
                          (channel) => channel.id === drafts[pool].channel_id,
                        )?.name
                          ? `#${channels.find((channel) => channel.id === drafts[pool].channel_id)!.name}`
                          : channelsError
                            ? drafts[pool].channel_id || "No channel"
                            : "Checking channel…"
                      }
                      roles={
                        <>
                          {entry.role_ids.length
                            ? entry.role_ids
                                .map(
                                  (id) =>
                                    roles.items.find((role) => role.id === id)
                                      ?.name ||
                                    (roles.error
                                      ? `Role ${id}`
                                      : "Checking role…"),
                                )
                                .join(", ")
                            : "No roles notified"}
                          {roles.error && (
                            <Button onClick={roles.retry}>
                              Retry role names
                            </Button>
                          )}
                        </>
                      }
                      dashboardLink={
                        drafts[pool].roster_url ===
                        dashboardRosterUrl(window.location.origin, seasonId)
                      }
                      status={
                        <>
                          <span>
                            {deletedPools.includes(pool)
                              ? "The post was deleted. You can send it again."
                              : announcementDeliveryStatus(
                                  delivery,
                                  bridge.published_version,
                                )}
                          </span>
                          {safeMessageUrl(delivery?.message_url) && (
                            <a
                              href={delivery!.message_url!}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              View in Discord ↗
                            </a>
                          )}
                        </>
                      }
                      canSend={readyPools.includes(pool)}
                      retry={
                        delivery?.status === "failed" ||
                        delivery?.status === "stale"
                      }
                      onPreview={() => setExpandedPreview(pool)}
                      onSend={() => setSendReview([pool])}
                      onEdit={(trigger) => {
                        if (
                          isSecureOrigin() &&
                          !locked &&
                          !drafts[pool].roster_url
                        )
                          setDraft(pool, {
                            roster_url: dashboardRosterUrl(
                              window.location.origin,
                              seasonId,
                            ),
                          });
                        setEditor({ pool, trigger });
                        setNotice(null);
                      }}
                    />
                  );
                })}
              </div>
              <Button
                icon={Send}
                variant="primary"
                disabled={!readyPools.length}
                onClick={() => setSendReview(readyPools)}
              >
                {readyPools.length > 1
                  ? "Review both pools"
                  : "Review and send"}
              </Button>
              {!readyPools.length && (
                <p className="announcement-muted">
                  No pools are ready. Check publication, message settings and
                  delivery status above.
                </p>
              )}
              {draftGeneration !== bridge.generation && (
                <p className="notice error">
                  Settings changed elsewhere. Copy your edits, then refresh and
                  review.
                </p>
              )}
            </>
          )}
        </>
      )}
      {canDeclare &&
        onDeclaration &&
        bridge?.published_version === publicationVersion &&
        pools.some(
          (pool) => bridge?.pools[pool].delivery?.status === "sent",
        ) && (
          <button
            className="cwl-next-cue"
            disabled={busy}
            onClick={onDeclaration}
          >
            Next: Declaration check ›
          </button>
        )}
      {sendReview && bridge && (
        <AnnouncementSendReview
          cycle={bridge.cycle || ""}
          version={bridge.published_version}
          pools={sendReview.map((pool) => ({
            key: pool,
            label: poolLabel(pool),
            destination:
              channels.find((channel) => channel.id === drafts[pool].channel_id)
                ?.name || drafts[pool].channel_id,
            roleNames: bridge.pools[pool].role_ids.map(
              (id) =>
                roles.items.find((role) => role.id === id)?.name ||
                `Role ${id}`,
            ),
            clans: bridge.pools[pool].sequence?.published_clans,
            preview: preview(pool),
          }))}
          onCancel={() => setSendReview(null)}
          onConfirm={() => {
            void sendBoth(sendReview);
          }}
        />
      )}
      {editor && bridge && (
        <AnnouncementEditor
          key={editor.pool}
          pool={editor.pool}
          trigger={editor.trigger}
          draft={drafts[editor.pool]}
          channels={channels}
          locked={["sent", "pending", "sending", "uncertain"].includes(
            bridge.pools[editor.pool].delivery?.status || "",
          )}
          editable={
            canManage &&
            !busy &&
            !loading &&
            !bridgeError &&
            !channelsError &&
            channels.length > 0 &&
            draftGeneration === bridge.generation &&
            !["sent", "pending", "sending", "uncertain"].includes(
              bridge.pools[editor.pool].delivery?.status || "",
            )
          }
          busy={busy}
          changed={unsaved(editor.pool)}
          testAllowed={
            canManage &&
            !busy &&
            !loading &&
            !bridgeError &&
            !channelsError &&
            draftGeneration === bridge.generation
          }
          testChannel={testChannel}
          testUrl={safeMessageUrl(testUrl) ? testUrl : ""}
          onTestChannel={setTestChannel}
          notice={
            notice && (
              <p role={notice.kind === "error" ? "alert" : "status"}>
                {notice.text}
              </p>
            )
          }
          onDraft={(update) => setDraft(editor.pool, update)}
          onClose={() => setEditor(null)}
          onSave={() => void save(editor.pool)}
          onTest={() => setConfirmation(editor.pool)}
        />
      )}
      {confirmation && (
        <ConfirmDialog
          heading={
            confirmation === "refresh" ? "Reload announcements" : "Send test"
          }
          text={
            confirmation === "refresh"
              ? "Discard unsaved announcement edits and reload?"
              : `Send a ${confirmation === "main" ? "Main" : "Lazy"} test to #${channels.find((channel) => channel.id === testChannel)?.name || testChannel}? No roles are pinged and the real announcement stays unsent.`
          }
          disabled={busy || loading}
          onCancel={() => setConfirmation(null)}
          onConfirm={() => {
            if (confirmation === "refresh") refresh();
            else void sendTest(confirmation);
          }}
        />
      )}
      {confirmMonth && (
        <ConfirmDialog
          text={`Change this season's Manage CWL settings from ${bridge?.cycle || "no month"} to ${cycleInput}? Review both pool templates before sending.${pools.some(unsaved) ? " Unsaved message edits will be discarded." : ""}`}
          onCancel={() => setConfirmMonth(false)}
          onConfirm={() => void bindCycle()}
          disabled={busy || loading}
        />
      )}
      {expandedPreview && (
        <AnnouncementPreviewDialog
          title={`${poolLabel(expandedPreview)} preview`}
          onClose={() => setExpandedPreview(null)}
        >
          {preview(expandedPreview)}
        </AnnouncementPreviewDialog>
      )}
    </section>
  );
}
