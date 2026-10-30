import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import ConfirmDialog from "./ConfirmDialog";
import type { AnnouncementChannel } from "./announcements";
import ScheduleEditor from "./warReminders/ScheduleEditor";
import CopyReminders from "./warReminders/CopyReminders";
import TestPanel from "./warReminders/TestPanel";
import DeliveryHistory from "./warReminders/DeliveryHistory";
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
  useEffect(() => {
    onBusy?.(busy || testBusy || copyBusy);
    return () => onBusy?.(false);
  }, [busy, testBusy, copyBusy, onBusy]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const saving = useRef(false);
  const historyGeneration = useRef(0);
  const dirty =
    !!draft && JSON.stringify(draft) !== JSON.stringify(data?.settings);

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
    if (!draft || !data || saving.current) return false;
    saving.current = true;
    const turn = ++generation.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<ReminderData>(base, "PUT", {
        settings: draft,
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

  const changes =
    draft && data
      ? Object.keys(draft).filter(
          (key) =>
            JSON.stringify(draft[key as keyof ReminderSettings]) !==
            JSON.stringify(data.settings[key as keyof ReminderSettings]),
        ).length
      : 0;
  useEffect(() => {
    onEditor?.({
      changes,
      summary: draft
        ? `${draft.enabled ? "On" : "Off"} · ${draft.minutes.length} times`
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
            Reload
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
            ? "Reminders could not be loaded. Use Reload to try again."
            : "Loading reminders…"}
        </p>
      ) : (
        <>
          <ScheduleEditor
            settings={draft}
            channels={channels}
            disabled={busy || testBusy || copyBusy || disabled}
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
                disabled={busy || testBusy || copyBusy || disabled || !dirty}
                onClick={() => void save()}
              >
                Save reminders
              </button>
            </div>
          )}
          <CopyReminders
            key={tag}
            base={base}
            source={data}
            disabled={disabled || busy || testBusy || dirty}
            onBusy={setCopyBusy}
          />
          <DeliveryHistory data={data} enabled={data.settings.enabled} />
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
              Preview &amp; send a test{testBusy ? " · Sending…" : ""}
            </summary>
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
