import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import ConfirmDialog from "./ConfirmDialog";
import type { AnnouncementChannel } from "./announcements";
import ScheduleEditor from "./warReminders/ScheduleEditor";
import CopyReminders from "./warReminders/CopyReminders";
import TestPanel from "./warReminders/TestPanel";
import DeliveryHistory, {
  DeliveryStatus,
  historySummary,
} from "./warReminders/DeliveryHistory";
import type { ReminderData, ReminderSettings } from "./warReminders/types";
import "./WarReminders.css";

export type ReminderEditor = {
  changes: number;
  summary: string;
  save: () => Promise<boolean>;
  discard: () => void;
};
type Props = {
  onEditor?: (editor: ReminderEditor | null) => void;
  embedded?: boolean;
  active?: boolean;
  disabled?: boolean;
  tag: string;
  channels: AnnouncementChannel[];
  onDirty: (dirty: boolean) => void;
  onBusy?: (busy: boolean) => void;
};

export default function WarReminders({
  tag,
  channels,
  onDirty,
  onBusy,
  disabled = false,
  embedded = false,
  active = true,
  onEditor,
}: Props) {
  const base = "/manage/clans/" + encodeURIComponent(tag) + "/war-reminders";
  const [data, setData] = useState<ReminderData | null>(null);
  const [draft, setDraft] = useState<ReminderSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [copyBusy, setCopyBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [switchBusy, setSwitchBusy] = useState(false);
  const [switchError, setSwitchError] = useState("");
  useEffect(() => {
    onBusy?.(busy || testBusy || copyBusy || switchBusy);
    return () => onBusy?.(false);
  }, [busy, testBusy, copyBusy, switchBusy, onBusy]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const saving = useRef(false);
  const switching = useRef(false);
  const historyGeneration = useRef(0);
  // The On/Off switch saves at once, so it never counts as an unsaved change.
  const changedKeys =
    draft && data
      ? (Object.keys(draft) as (keyof ReminderSettings)[]).filter(
          (key) =>
            key !== "enabled" &&
            JSON.stringify(draft[key]) !== JSON.stringify(data.settings[key]),
        )
      : [];
  const dirty = changedKeys.length > 0;

  const load = useCallback(async () => {
    const turn = ++generation.current;
    setBusy(true);
    try {
      const result = await api<ReminderData>(base);
      if (turn !== generation.current) return;
      setData(result);
      setDraft(result.settings);
      setError("");
    } catch (e) {
      if (turn === generation.current) setError((e as Error).message);
    } finally {
      if (turn === generation.current) setBusy(false);
    }
  }, [base]);

  useEffect(() => {
    void load();
    return () => {
      ++generation.current;
    };
  }, [load]);

  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);

  const refreshHistory = useCallback(async () => {
    const turn = generation.current;
    const historyTurn = ++historyGeneration.current;
    const result = await api<ReminderData>(base);
    if (
      turn === generation.current &&
      historyTurn === historyGeneration.current
    ) {
      setData((old) =>
        old ? { ...old, history: result.history, status: result.status } : old,
      );
    }
  }, [base]);

  useEffect(() => {
    if (!data || !active) return;
    const timer = setInterval(() => {
      if (!document.hidden) void refreshHistory().catch(() => {});
    }, 15000);
    return () => clearInterval(timer);
  }, [!!data, active, refreshHistory]);

  async function save() {
    if (!draft || !data || saving.current || switching.current) return false;
    saving.current = true;
    const turn = ++generation.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<ReminderData>(base, "PUT", {
        settings: { ...draft, enabled: data.settings.enabled },
        revision: data.revision,
      });
      if (turn !== generation.current) return false;
      setData(result);
      setDraft(result.settings);
      setNotice("War reminders saved.");
      return true;
    } catch (e) {
      if (turn === generation.current)
        setError(e instanceof Error ? e.message : "Could not save reminders.");
      return false;
    } finally {
      saving.current = false;
      if (turn === generation.current) setBusy(false);
    }
  }

  const changes = changedKeys.length;
  async function toggleEnabled(next: boolean) {
    if (!data || saving.current || switching.current) return;
    switching.current = true;
    setSwitchBusy(true);
    setSwitchError("");
    setError("");
    setNotice("");
    setDraft((current) => (current ? { ...current, enabled: next } : current));
    try {
      const result = await api<ReminderData>(base, "PUT", {
        settings: { ...data.settings, enabled: next },
        revision: data.revision,
      });
      setData(result);
      // Keep every other unsaved edit; only the saved On/Off state is applied.
      setDraft((current) =>
        current ? { ...current, enabled: result.settings.enabled } : current,
      );
    } catch (e) {
      setDraft((current) =>
        current ? { ...current, enabled: data.settings.enabled } : current,
      );
      const message =
        e instanceof Error ? e.message : "Could not save. Try again.";
      if (e instanceof ApiError && e.status === 409) setError(message);
      else setSwitchError(message);
    } finally {
      switching.current = false;
      setSwitchBusy(false);
    }
  }
  useEffect(() => {
    onEditor?.({
      changes,
      summary: draft
        ? `${draft.enabled ? "On" : "Off"} · ${draft.minutes.length} ${draft.minutes.length === 1 ? "time" : "times"}${draft.enabled ? "" : " saved"}`
        : "Loading…",
      save,
      discard: () => {
        if (!saving.current) {
          setDraft(data?.settings || null);
          setError("");
        }
      },
    });
    return () => onEditor?.(null);
  }, [onEditor, draft, data]);
  const [confirmReload, setConfirmReload] = useState(false);

  function reload() {
    if (dirty) {
      setConfirmReload(true);
      return;
    }
    void load();
  }

  return (
    <section className="war-reminders" aria-label="War reminders">
      {error && (
        <p className="notice error" role="alert">
          {error}{" "}
          <button disabled={busy} onClick={reload}>
            Refresh
          </button>
        </p>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      {!draft || !data ? (
        <p role="status">
          {error
            ? "Reminders could not be loaded. Use Refresh to try again."
            : "Loading reminders…"}
        </p>
      ) : (
        <>
          <ScheduleEditor
            settings={draft}
            channels={channels}
            disabled={busy || testBusy || copyBusy || disabled}
            hasChannel={!!data.settings.channel_id}
            switchBusy={switchBusy}
            switchError={switchError}
            onToggle={(next) => void toggleEnabled(next)}
            onChange={(patch) =>
              setDraft((current) =>
                current ? { ...current, ...patch } : current,
              )
            }
          />
          {!embedded && (
            <div className="clan-actions">
              <small>
                {dirty ? "Unsaved reminder changes" : "Reminder settings saved"}
              </small>
              <button
                className="primary"
                disabled={
                  busy ||
                  testBusy ||
                  copyBusy ||
                  switchBusy ||
                  disabled ||
                  !dirty
                }
                onClick={() => void save()}
              >
                Save reminders
              </button>
            </div>
          )}
          <DeliveryStatus data={data} enabled={data.settings.enabled} />
          <details
            className="war-disclosure"
            onToggle={(event) => setTestOpen(event.currentTarget.open)}
          >
            <summary
              aria-disabled={testBusy}
              onClick={(event) => {
                if (testBusy) event.preventDefault();
              }}
            >
              {historySummary(data)}
              {testBusy ? " · Sending…" : ""}
            </summary>
            <DeliveryHistory data={data} />
            <TestPanel
              channelName={
                channels.find((channel) => channel.id === draft.channel_id)
                  ?.name || ""
              }
              base={base}
              settings={draft}
              active={active && testOpen}
              disabled={busy || copyBusy || disabled}
              onDelivered={refreshHistory}
              onBusy={setTestBusy}
            />
          </details>
          <CopyReminders
            key={tag}
            base={base}
            source={data}
            disabled={disabled || busy || testBusy || switchBusy || dirty}
            onBusy={setCopyBusy}
          />
        </>
      )}
      {confirmReload && (
        <ConfirmDialog
          text="Discard unsaved war reminder changes?"
          confirmLabel="Discard"
          onCancel={() => setConfirmReload(false)}
          onConfirm={() => {
            setConfirmReload(false);
            void load();
          }}
        />
      )}
    </section>
  );
}
