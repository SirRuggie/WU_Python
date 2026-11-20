import LoadError from "./LoadError";
import SectionTabs, { SectionTabPanel } from "./SectionTabs";
import { targetCwlMonth } from "./reminders/reminderFormat";
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
import { api, ApiError } from "./api";
import type { AnnouncementChannel } from "./announcements";
import {
  campaignPatch,
  type Campaign,
  type CampaignState,
} from "./reminderCampaign";
import "./ReminderWorkspace.css";

/** Treat malformed successful option responses as unavailable, never as deleted names. */
function checkedReminderLookup<T extends { id: string; name: string }>(lookup: {
  items: T[];
  error: string;
  loading: boolean;
  retry: () => void;
}) {
  const valid =
    Array.isArray(lookup.items) &&
    lookup.items.every(
      (item) =>
        item !== null &&
        typeof item === "object" &&
        typeof item.id === "string" &&
        typeof item.name === "string",
    );
  return valid
    ? lookup
    : {
        ...lookup,
        items: [] as T[],
        error:
          lookup.error || (lookup.loading ? "" : "Could not load options."),
      };
}

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
  const channelLookup = checkedReminderLookup(
    useReminderLookup<AnnouncementChannel>(
      "/announcement-channels",
      "channels",
    ),
  );
  const roleLookup = checkedReminderLookup(
    useReminderLookup<{ id: string; name: string }>(
      "/announcement-roles",
      "roles",
    ),
  );
  const acting = useRef(false);
  const loadRequest = useRef(0);
  const [tab, setTab] = useState<"messages" | "schedule" | "history">(
    "messages",
  );
  const [invalidFields, setInvalidFields] = useState<Set<string>>(new Set());
  const [loadEpoch, setLoadEpoch] = useState(0);
  const [saveError, setSaveError] = useState("");
  const setFieldInvalid = useCallback((id: string, invalid: boolean) => {
    setInvalidFields((current) => {
      if (current.has(id) === invalid) return current;
      const next = new Set(current);
      if (invalid) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);
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
      setInvalidFields(new Set());
      setLoadEpoch((value) => value + 1);
      setSaveError("");
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
    setInvalidFields(new Set());
    setLoadEpoch((value) => value + 1);
    setSaveError("");
    setTab("messages");
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
  const dirty = Object.keys(patch).length > 0 || invalidFields.size > 0;
  const protectedBusy = busy && !!state;
  useEffect(() => {
    onDirty(dirty || protectedBusy);
    return () => onDirty(false);
  }, [dirty, protectedBusy, onDirty]);
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
    setSaveError("");
    setDraft(next);
    setError("");
    setPreview(null);
    setNotice("");
  };
  const saveAct = (work: () => Promise<void>) =>
    act(async () => {
      setSaveError("");
      try {
        await work();
      } catch (cause) {
        setSaveError(errorText(cause));
        throw cause;
      }
    });
  const refresh = () => {
    if (!dirty) void act(load);
    else
      setConfirmation({
        text: "Discard unsaved reminder edits and reload the saved reminders?",
        action: () => void act(load),
      });
  };
  const body = { generation: state?.generation, patch, repeat_monthly: true };
  const disabled = busy || archived;
  const schedule = preview?.schedule || state?.schedule || [];
  return (
    <section className="reminders-workspace">
      <LoadError
        message={error}
        onRetry={state ? undefined : () => void act(load)}
        disabled={busy}
      />
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
                id="reminder-sections"
                className="tabs workflow-tabs section-tabs--flow"
                label="Reminder sections"
                items={[
                  { id: "messages", label: "Messages" },
                  { id: "schedule", label: "Schedule" },
                  { id: "history", label: "History" },
                ]}
                value={tab}
                onChange={setTab}
                allPanelsMounted
                revealSelection
              />
              <SectionTabPanel
                id="reminder-sections"
                value="messages"
                hidden={tab !== "messages"}
              >
                <ReminderMessagesTab
                  key={base}
                  draft={draft}
                  saved={state.campaign!}
                  schedule={schedule}
                  activated={state.activated}
                  seasonId={seasonId}
                  active={tab === "messages"}
                  busy={busy}
                  disabled={disabled}
                  channelLookup={channelLookup}
                  roleLookup={roleLookup}
                  edit={edit}
                  previewDeadline={preview?.deadline || state.deadline}
                  onRefresh={refresh}
                />
              </SectionTabPanel>
              <SectionTabPanel
                id="reminder-sections"
                value="schedule"
                hidden={tab !== "schedule"}
              >
                <ReminderScheduleTab
                  key={`${base}:${loadEpoch}`}
                  draft={draft}
                  cycle={state.cycle}
                  signupOpen={state.signup_open}
                  disabled={disabled}
                  edit={edit}
                  schedule={schedule}
                  onInvalidChange={setFieldInvalid}
                />
                {!preview && (
                  <ReminderSchedulePanel
                    draft={draft}
                    preview={null}
                    timeZone={draft.timezone}
                    schedule={schedule}
                    sentOccurrences={state.sent_occurrences}
                    skipped={state.skipped}
                  />
                )}
                <details className="reminder-disclosure reminder-context">
                  <summary>
                    About this schedule · {targetCwlMonth(state.cycle)} CWL
                  </summary>
                  <p>
                    Saved settings repeat every month. Specific dates are
                    converted to monthly rules for future months. Existing
                    signup links stay unchanged. Previously sent messages are
                    not resent.
                  </p>
                </details>
              </SectionTabPanel>
              <SectionTabPanel
                id="reminder-sections"
                value="history"
                hidden={tab !== "history"}
              >
                <h2>History</h2>
                <ReminderDeliveryHistory history={state.history} />
              </SectionTabPanel>
              {tab !== "history" && (
                <>
                  {preview && (
                    <ReminderSchedulePanel
                      draft={draft}
                      preview={preview}
                      timeZone={tab === "schedule" ? draft.timezone : undefined}
                      schedule={schedule}
                      sentOccurrences={state.sent_occurrences}
                      skipped={state.skipped}
                    />
                  )}
                  {(dirty || saveError) && (
                    <ReminderSaveBar
                      base={base}
                      state={state}
                      patch={patch}
                      body={body}
                      dirty={dirty}
                      preview={preview}
                      error={saveError}
                      busy={busy}
                      disabled={disabled || invalidFields.size > 0}
                      act={saveAct}
                      load={load}
                      setPreview={setPreview}
                      setNotice={setNotice}
                      setConfirmation={setConfirmation}
                    />
                  )}
                </>
              )}
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
