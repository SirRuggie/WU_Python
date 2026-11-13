import SectionTabs from "./SectionTabs";
import { dashboardPath } from "./dashboardHistory";
import SignupReminderOverview, {
  targetCwlMonth,
} from "./reminders/SignupReminderOverview";
import ReminderDeliveryHistory from "./reminders/ReminderDeliveryHistory";
import ReminderMessagesTab from "./reminders/ReminderMessagesTab";
import ReminderSaveBar from "./reminders/ReminderSaveBar";
import ReminderSchedulePanel from "./reminders/ReminderSchedulePanel";
import ReminderScheduleTab from "./reminders/ReminderScheduleTab";
import ReminderStatusBar from "./reminders/ReminderStatusBar";
import {
  clone,
  errorText,
  type Confirmation,
} from "./reminders/reminderWorkspaceHelpers";
import ConfirmDialog from "./ConfirmDialog";
import { useReminderLookup } from "./useReminderLookups";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Pool } from "./api";
import type { AnnouncementChannel } from "./announcements";
import {
  campaignPatch,
  type Campaign,
  type CampaignState,
  type Variant,
} from "./reminderCampaign";
import "./ReminderWorkspace.css";

export default function ReminderWorkspace({
  seasonId,
  archived,
  onDirty,
}: {
  seasonId: string;
  archived: boolean;
  onDirty: (dirty: boolean) => void;
}) {
  const base = `/seasons/${encodeURIComponent(seasonId)}/manage-reminders`;
  const [state, setState] = useState<CampaignState | null>(null);
  const [draft, setDraft] = useState<Campaign | null>(null);
  const [preview, setPreview] = useState<CampaignState | null>(null);
  const channelLookup = useReminderLookup<AnnouncementChannel>(
    "/announcement-channels",
    "channels",
  );
  const roleLookup = useReminderLookup<{ id: string; name: string }>(
    "/announcement-roles",
    "roles",
  );
  const channels = channelLookup.items,
    roles = roleLookup.items;
  const channelError = channelLookup.error;
  const acting = useRef(false);
  const loadRequest = useRef(0);
  const [tab, setTab] = useState<
    "overview" | "messages" | "schedule" | "history"
  >("overview");
  const [messageId, setMessageId] = useState("signup");
  const [pool, setPool] = useState<Pool>("main");
  const [roleText, setRoleText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const load = useCallback(async () => {
    const request = ++loadRequest.current;
    try {
      const data = await api<CampaignState>(base);
      if (request !== loadRequest.current) return;
      setState(data);
      setDraft(data.campaign ? clone(data.campaign) : null);
      setPreview(null);
    } catch (cause) {
      if (
        request === loadRequest.current &&
        cause instanceof ApiError &&
        [401, 403].includes(cause.status)
      ) {
        setState(null);
        setDraft(null);
        setPreview(null);
      }
      throw cause;
    }
  }, [base]);
  useEffect(() => {
    let alive = true;
    const request = ++loadRequest.current;
    setState(null);
    setDraft(null);
    setPreview(null);
    setError("");
    setBusy(true);
    api<CampaignState>(base)
      .then((data) => {
        if (!alive || request !== loadRequest.current) return;
        setState(data);
        setDraft(data.campaign ? clone(data.campaign) : null);
      })
      .catch((cause) => {
        if (!alive || request !== loadRequest.current) return;
        setError(errorText(cause));
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
          setState(null);
          setDraft(null);
        }
      })
      .finally(() => {
        if (alive && request === loadRequest.current) setBusy(false);
      });
    return () => {
      alive = false;
      loadRequest.current += 1;
    };
  }, [base]);
  const patch =
    state?.campaign && draft ? campaignPatch(state.campaign, draft) : {};
  const dirty = Object.keys(patch).length > 0;
  const protectedBusy = busy && !!state;
  useEffect(() => {
    onDirty(dirty || protectedBusy);
    return () => onDirty(false);
  }, [dirty, protectedBusy, onDirty]);
  useEffect(() => {
    setRoleText(
      draft?.messages[messageId]?.variants[pool]?.role_ids.join(", ") || "",
    );
  }, [messageId, pool, state]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    if (!state?.cycle || !state.activated || state.schedule_synced || busy)
      return;
    let active = true;
    const timer = window.setTimeout(() => {
      api<CampaignState>(base)
        .then((data) => {
          if (!active) return;
          setState((current) =>
            current && data.generation === current.generation
              ? {
                  ...current,
                  worker_ready: data.worker_ready,
                  schedule_synced: data.schedule_synced,
                  schedule_sync_at: data.schedule_sync_at,
                }
              : current,
          );
        })
        .catch((cause) => {
          if (
            !active ||
            !(cause instanceof ApiError) ||
            ![401, 403].includes(cause.status)
          )
            return;
          setState(null);
          setDraft(null);
          setPreview(null);
          setError(errorText(cause));
        });
    }, 10000);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [base, state, busy]);
  const act = async (work: () => Promise<void>) => {
    if (acting.current) return;
    acting.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (cause) {
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
        setState(null);
        setDraft(null);
        setPreview(null);
      }
      setError(errorText(cause));
    } finally {
      acting.current = false;
      setBusy(false);
    }
  };
  const edit = (next: Campaign) => {
    setDraft(next);
    setError("");
    setPreview(null);
    setNotice("");
  };
  const changeVariant = (change: Partial<Variant>) => {
    if (!draft) return;
    const next = clone(draft);
    Object.assign(next.messages[messageId].variants[pool], change);
    edit(next);
  };
  const body = { generation: state?.generation, patch, repeat_monthly: true };
  const disabled = busy || archived;
  const schedule = preview?.schedule || state?.schedule || [];
  const destination = (id: string) => {
    if (!id) return "No channel chosen";
    return (
      channels.find((channel) => channel.id === id)?.name || `Channel ${id}`
    );
  };
  const recipient = (ids: string[]) => {
    if (!ids.length) return "No role mentions";
    const labels = ids
      .slice(0, 2)
      .map((id) => roles.find((role) => role.id === id)?.name || `Role ${id}`);
    return `${labels.join(", ")}${ids.length > 2 ? ` +${ids.length - 2} more` : ""}`;
  };
  return (
    <section className="reminders-workspace">
      {error && (
        <p className="notice error" role="alert">
          {error}
          {!state && (
            <button onClick={() => void act(load)} disabled={busy}>
              Retry loading reminders
            </button>
          )}
        </p>
      )}
      {notice && (
        <p className="notice success" role="status">
          {notice}
        </p>
      )}
      {busy && (
        <p className="working-status" role="status">
          Working…
        </p>
      )}
      {state?.warning && (
        <p className="notice error" role="alert">
          {state.warning}
        </p>
      )}
      {state && (
        <>
          {draft && (
            <>
              <ReminderStatusBar
                base={base}
                state={state}
                draft={draft}
                dirty={dirty}
                busy={busy}
                disabled={disabled}
                act={act}
                load={load}
                setNotice={setNotice}
                setConfirmation={setConfirmation}
              />
              {archived && (
                <p className="notice">
                  This season is archived. Settings are read-only.
                </p>
              )}
              <SectionTabs
                className="tabs workflow-tabs section-tabs--flow"
                label="Reminder sections"
                items={(
                  ["overview", "messages", "schedule", "history"] as const
                ).map((value) => {
                  return {
                    id: value,
                    label: (
                      <>
                        {value === "overview"
                          ? "Overview"
                          : value === "messages"
                            ? "Messages"
                            : value === "schedule"
                              ? "Schedule"
                              : "Delivery history"}
                      </>
                    ),
                  };
                })}
                value={tab}
                onChange={(value) => {
                  setTab(value);
                }}
                revealSelection
              />
              {tab === "overview" && (
                <>
                  <SignupReminderOverview
                    activated={state.activated}
                    campaign={draft}
                    cycle={state.cycle}
                    schedule={schedule}
                    destination={destination}
                    recipient={recipient}
                    onEdit={(id, audience) => {
                      setMessageId(id);
                      setPool(audience);
                      setTab("messages");
                    }}
                    onTiming={() => setTab("schedule")}
                  />
                  {(channelError || roleLookup.error) && (
                    <p className="reminder-lookup-warning" role="status">
                      Channel or role names are unavailable. Open a message to
                      retry the lookup.
                    </p>
                  )}
                  <p className="reminder-overview-note">
                    Roster posts are on{" "}
                    <a
                      href={dashboardPath({
                        view: "publication",
                        step: "announce",
                        season: seasonId,
                      })}
                    >
                      Announcements ›
                    </a>
                  </p>
                  <p className="reminder-overview-note">
                    Delivery is confirmed in Delivery history. Dashboard signups
                    are {state.signup_open ? "open" : "closed"} separately.
                  </p>
                </>
              )}
              {tab === "messages" && (
                <ReminderMessagesTab
                  draft={draft}
                  messageId={messageId}
                  setMessageId={setMessageId}
                  pool={pool}
                  setPool={setPool}
                  disabled={disabled}
                  channels={channels}
                  roles={roles}
                  channelLookup={channelLookup}
                  roleLookup={roleLookup}
                  roleText={roleText}
                  setRoleText={setRoleText}
                  edit={edit}
                  changeVariant={changeVariant}
                  previewDeadline={preview?.deadline || state.deadline}
                />
              )}
              {tab === "schedule" && (
                <ReminderScheduleTab
                  draft={draft}
                  cycle={state.cycle}
                  signupOpen={state.signup_open}
                  disabled={disabled}
                  edit={edit}
                />
              )}
              {tab === "history" && (
                <div className="card">
                  <h3>Shared delivery history</h3>
                  <p>
                    Refresh to check delivery. This page does not send messages.
                  </p>
                  <ReminderDeliveryHistory history={state.history} />
                </div>
              )}
              {tab !== "history" && (tab !== "overview" || dirty) && (
                <ReminderSaveBar
                  base={base}
                  state={state}
                  patch={patch}
                  body={body}
                  dirty={dirty}
                  preview={preview}
                  error={error}
                  busy={busy}
                  disabled={disabled}
                  act={act}
                  load={load}
                  setPreview={setPreview}
                  setNotice={setNotice}
                  setConfirmation={setConfirmation}
                />
              )}
              {tab === "schedule" || preview ? (
                <ReminderSchedulePanel
                  draft={draft}
                  preview={preview}
                  schedule={schedule}
                  sentOccurrences={state.sent_occurrences}
                  skipped={state.skipped}
                />
              ) : null}
              <details className="reminder-disclosure reminder-context">
                <summary>
                  About this schedule · {targetCwlMonth(state.cycle)} CWL
                </summary>
                <p>
                  Messages and times repeat monthly. Existing signup links stay
                  unchanged. Previously sent messages are not resent.
                </p>
              </details>
            </>
          )}
        </>
      )}
      {confirmation && (
        <ConfirmDialog
          confirmLabel={confirmation.confirmLabel}
          text={confirmation.text}
          onCancel={() => setConfirmation(null)}
          onConfirm={() => {
            const action = confirmation.action;
            setConfirmation(null);
            action();
          }}
        />
      )}
    </section>
  );
}
