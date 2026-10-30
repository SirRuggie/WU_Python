import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { AnnouncementChannel } from "./announcements";
import ScheduleEditor from "./warReminders/ScheduleEditor";
import TestPanel from "./warReminders/TestPanel";
import DeliveryHistory from "./warReminders/DeliveryHistory";
import type { ReminderData, ReminderSettings } from "./warReminders/types";
import "./WarReminders.css";

type Props = {
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
}: Props) {
  const base = "/manage/clans/" + encodeURIComponent(tag) + "/war-reminders";
  const [data, setData] = useState<ReminderData | null>(null);
  const [draft, setDraft] = useState<ReminderSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  useEffect(() => {
    onBusy?.(busy || testBusy);
    return () => onBusy?.(false);
  }, [busy, testBusy, onBusy]);
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
    if (!data) return;
    const timer = setInterval(() => {
      if (!document.hidden) void refreshHistory().catch(() => {});
    }, 15000);
    return () => clearInterval(timer);
  }, [!!data, refreshHistory]);

  async function save() {
    if (!draft || !data || saving.current) return;
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
      if (turn !== generation.current) return;
      setData(result);
      setDraft(result.settings);
      setNotice("War reminders saved.");
    } catch (e) {
      if (turn === generation.current)
        setError(e instanceof Error ? e.message : "Could not save reminders.");
    } finally {
      saving.current = false;
      if (turn === generation.current) setBusy(false);
    }
  }

  function reload() {
    if (dirty && !confirm("Discard reminder edits and reload?")) return;
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
            disabled={busy || testBusy || disabled}
            onChange={(patch) =>
              setDraft((current) =>
                current ? { ...current, ...patch } : current,
              )
            }
          />
          <div className="clan-actions">
            <small>
              {dirty ? "Unsaved reminder changes" : "Reminder settings saved"}
            </small>
            <button
              className="primary"
              disabled={busy || testBusy || disabled || !dirty}
              onClick={() => void save()}
            >
              Save reminders
            </button>
          </div>
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
              active={testOpen}
              disabled={busy || disabled}
              onDelivered={refreshHistory}
              onBusy={setTestBusy}
            />
          </details>
        </>
      )}
    </section>
  );
}
