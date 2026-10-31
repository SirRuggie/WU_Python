import { useEffect, useRef, useState } from "react";
import ConfirmDialog from "./ConfirmDialog";
import { relativeTime } from "./commandTime";
import { api } from "./api";
import "./ChangeHistory.css";
type Entry = {
  id: string;
  actor_name: string;
  at: string;
  action: string;
  status: string;
  changed: string[];
  before: Record<string, unknown>;
  after: Record<string, unknown>;
};
export function supportsHistory(target: string) {
  return (
    /\/manage\/content\/[^/]+$/.test(target) ||
    /\/manage\/operations\/(fwa_weight|fwa_bases|fwa_points|fwa_sync)(\/(?!new$)[\w-]+)?$/.test(
      target,
    ) ||
    /\/manage\/ticket-settings\/(timers|main|fwa|viewers)$/.test(target) ||
    /\/manage\/text-commands\/[^/]+$/.test(target)
  );
}
const display = (value: unknown) =>
  value === undefined || value === null || value === ""
    ? "Empty"
    : typeof value === "object"
      ? JSON.stringify(value, null, 2)
      : typeof value === "boolean"
        ? value
          ? "On"
          : "Off"
        : String(value);
export default function ChangeHistory({
  target,
  revision,
  labels = {},
  disabled,
  onRestored,
  onBusy,
}: {
  target: string;
  revision: string | number;
  labels?: Record<string, string>;
  disabled: boolean;
  onRestored: () => Promise<void>;
  onBusy: (value: boolean) => void;
}) {
  const [open, setOpen] = useState(false),
    [entries, setEntries] = useState<Entry[]>([]),
    [selected, setSelected] = useState(""),
    [loading, setLoading] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [pending, setPending] = useState("");
  const [confirmSide, setConfirmSide] = useState<"before" | "after" | null>(
    null,
  );
  const requestId = useRef(""),
    checking = useRef(false);
  const query = "?target=" + encodeURIComponent(target);
  async function load() {
    setLoading(true);
    setError("");
    try {
      const data = await api<{ entries: Entry[] }>("/manage/history" + query);
      setEntries(data.entries);
      setSelected((current) =>
        data.entries.some((entry) => entry.id === current)
          ? current
          : data.entries[0]?.id || "",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load history.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    if (open) void load();
  }, [open, target, revision]);
  async function check() {
    if (!pending || checking.current) return;
    checking.current = true;
    try {
      const result = await api<{ status: string; message?: string }>(
        pending.replace(/^\/api\/cwl/, ""),
      );
      if (["done", "failed", "uncertain"].includes(result.status)) {
        setPending("");
        onBusy(false);
        if (result.status === "done") {
          setNotice("Settings restored.");
          await onRestored();
          await load();
        } else
          setError(
            result.message ||
              "Restore was not confirmed. Reload the settings before trying again.",
          );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not check restore.");
    } finally {
      checking.current = false;
    }
  }
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => void check(), 2500);
    return () => window.clearInterval(timer);
  }, [pending]);
  async function restore(side: "before" | "after") {
    const entry = entries.find((row) => row.id === selected);
    if (!entry || disabled || busy || pending) return;
    setBusy(true);
    onBusy(true);
    setError("");
    setNotice("");
    let queued = false;
    requestId.current = crypto.randomUUID();
    try {
      const result = await api<{ status_url?: string }>(
        "/manage/history/restore" + query,
        "POST",
        { id: entry.id, side, revision, request_id: requestId.current },
      );
      if (result.status_url) {
        queued = true;
        setPending(result.status_url);
        setNotice("Waiting for the bot to restore settings…");
      } else {
        setNotice("Saved version restored.");
        await onRestored();
        await load();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not restore.");
    } finally {
      setBusy(false);
      if (!queued) onBusy(false);
    }
  }
  const entry = entries.find((row) => row.id === selected);
  return (
    <>
      <details
        className="change-history"
        open={open}
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary>History</summary>
        <p className="small">
          Saved edits from the dashboard and connected /manage editors appear
          here. Restoring does not publish a Discord post.
        </p>
        {loading && <p role="status">Loading history…</p>}
        {error && <p role="alert">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {!loading && !entries.length && !error && <p>No saved changes yet.</p>}
        {entries.length > 0 && (
          <>
            <label>
              Change to review
              <select
                value={selected}
                disabled={busy || !!pending}
                onChange={(event) => setSelected(event.target.value)}
              >
                {entries.map((row) => (
                  <option value={row.id} key={row.id}>
                    {new Date(row.at).toLocaleString()} · {row.actor_name} ·{" "}
                    {row.action === "restore"
                      ? "Restored"
                      : row.action === "discord_edit"
                        ? "Discord /manage"
                        : (
                            {
                              create: "Created",
                              delete: "Deleted",
                              on: "Turned on",
                              off: "Turned off",
                            } as Record<string, string>
                          )[row.action] || "Edited"}
                  </option>
                ))}
              </select>
            </label>
            {entry && (
              <>
                <p className="small">
                  by {entry.actor_name} · {relativeTime(entry.at)}
                </p>
                {entry.status !== "saved" ? (
                  <p role="status">
                    This save was not confirmed. Check the current settings.
                    Restore is unavailable.
                  </p>
                ) : (
                  <>
                    <div className="history-values">
                      {entry.changed.map((key) => (
                        <section key={key}>
                          <h4>
                            {labels[key] || key.replace(/[_.]/g, " ")}:{" "}
                            {display(entry.before[key]).slice(0, 80)} →{" "}
                            {display(entry.after[key]).slice(0, 80)}
                          </h4>
                          <div>
                            <div>
                              <strong>Before</strong>
                              <pre>{display(entry.before[key])}</pre>
                            </div>
                            <div>
                              <strong>After</strong>
                              <pre>{display(entry.after[key])}</pre>
                            </div>
                          </div>
                        </section>
                      ))}
                      {!entry.changed.length && <p>No values changed.</p>}
                    </div>
                    {disabled && (
                      <p>Save or discard your edits before restoring.</p>
                    )}
                    <div className="history-actions">
                      <button
                        disabled={disabled || busy || !!pending}
                        onClick={() => setConfirmSide("before")}
                      >
                        Restore before this change
                      </button>
                      {entry.action !== 'delete' && (
                      <button
                        disabled={disabled || busy || !!pending}
                        onClick={() => setConfirmSide("after")}
                      >
                        Restore this version
                      </button>
                      )}
                    </div>
                  </>
                )}
              </>
            )}
          </>
        )}
        {pending && (
          <button onClick={() => void check()}>Check restore status</button>
        )}
        <button
          disabled={loading || busy || !!pending}
          onClick={() => void load()}
        >
          Refresh history
        </button>
      </details>
      {confirmSide && (
        <ConfirmDialog
          text="Restore these saved settings? This replaces the current saved version. It does not send a Discord message."
          confirmLabel="Restore"
          onCancel={() => setConfirmSide(null)}
          onConfirm={() => {
            const side = confirmSide;
            setConfirmSide(null);
            void restore(side);
          }}
        />
      )}
    </>
  );
}
