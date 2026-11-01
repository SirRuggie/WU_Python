import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { Change, Run } from "./types";

export default function Standardize({
  disabled,
  onDenied,
}: {
  disabled: boolean;
  onDenied: () => void;
}) {
  const [open, setOpen] = useState(false),
    [preview, setPreview] = useState<{ token: string; rows: Change[] } | null>(
      null,
    ),
    [selected, setSelected] = useState<Set<string>>(new Set()),
    [run, setRun] = useState<Run | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [history, setHistory] = useState<
      { run_id: string; state: string; started_by?: string }[]
    >([]);
  const [reviewOnly, setReviewOnly] = useState(false);
  const alive = useRef(true),
    generation = useRef(0);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      generation.current++;
    };
  }, []);
  const fail = (e: unknown) => {
    if (!alive.current) return;
    if (e instanceof ApiError && [401, 403].includes(e.status)) {
      setPreview(null);
      setRun(null);
      setHistory([]);
      onDenied();
    } else
      setError(e instanceof Error ? e.message : "Standardize is unavailable.");
  };
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    api<{ runs: { run_id: string; state: string; started_by?: string }[] }>(
      "/manage/member-timezones/runs",
    )
      .then((result) => {
        if (!cancelled) setHistory(result.runs);
      })
      .catch(fail);
    return () => {
      cancelled = true;
    };
  }, [open]);
  useEffect(() => {
    if (!open || !run || ["done", "stopped"].includes(run.state)) return;
    let cancelled = false,
      inflight = false;
    const id = run.run_id;
    const load = async () => {
      if (cancelled || inflight || document.visibilityState === "hidden")
        return;
      inflight = true;
      const current = generation.current;
      try {
        const result = await api<Run>(
          `/manage/member-timezones/runs/${encodeURIComponent(id)}`,
        );
        if (!cancelled && generation.current === current) setRun(result);
      } catch (e) {
        if (!cancelled) fail(e);
      } finally {
        inflight = false;
      }
    };
    const timer = setInterval(() => void load(), 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [open, run?.run_id, run?.state]);
  async function build() {
    setBusy(true);
    setError("");
    const current = ++generation.current;
    try {
      const result = await api<{ token: string; rows: Change[] }>(
        "/manage/member-timezones/preview",
        "POST",
        {},
      );
      if (!alive.current || generation.current !== current) return;
      setPreview(result);
      setSelected(
        new Set(
          result.rows
            .filter((r) => !r.skip_reason && !r.needs_review)
            .map((r) => r.discord_id),
        ),
      );
      setRun(null);
    } catch (e) {
      fail(e);
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function confirm() {
    if (!preview) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ run_id: string; state: string }>(
        "/manage/member-timezones/confirm",
        "POST",
        { token: preview.token, selected: [...selected] },
      );
      const fresh = await api<Run>(
        `/manage/member-timezones/runs/${encodeURIComponent(result.run_id)}`,
      );
      if (alive.current) {
        setRun(fresh);
        setPreview(null);
      }
    } catch (e) {
      fail(e);
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function review(id: string) {
    setBusy(true);
    setError("");
    try {
      const result = await api<Run>(
        `/manage/member-timezones/runs/${encodeURIComponent(id)}`,
      );
      if (alive.current) {
        setRun(result);
        setPreview(null);
      }
    } catch (e) {
      fail(e);
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function stopRun() {
    if (!run) return;
    setBusy(true);
    setError("");
    const current = ++generation.current;
    try {
      await api(
        `/manage/member-timezones/runs/${encodeURIComponent(run.run_id)}/stop`,
        "POST",
        {},
      );
      const result = await api<Run>(
        `/manage/member-timezones/runs/${encodeURIComponent(run.run_id)}`,
      );
      if (alive.current && generation.current === current) setRun(result);
    } catch (e) {
      fail(e);
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  return (
    <section>
      {error && <p role="alert">{error}</p>}
      <details
        open={open}
        onToggle={(e) => {
          setOpen(e.currentTarget.open);
          if (!e.currentTarget.open) {
            generation.current++;
            setPreview(null);
          }
        }}
      >
        <summary>Standardize nicknames</summary>
        <p>
          Review every old → new nickname, then untick anyone to leave
          unchanged. The bot works one member at a time. Stop prevents new
          members from starting; the current member may finish. Stopped runs
          never resume. Uncertain changes require manual review and are never
          repeated automatically.
        </p>
        <button
          disabled={
            busy ||
            disabled ||
            ["queued", "stopping"].includes(run?.state || "")
          }
          onClick={() => void build()}
        >
          Preview all nickname changes
        </button>
        {history.length > 0 && (
          <label>
            Review a previous run
            <select
              value={run?.run_id || ""}
              disabled={busy || disabled}
              onChange={(e) => {
                if (e.target.value) void review(e.target.value);
              }}
            >
              <option value="">Choose a run</option>
              {history.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.state} · {r.run_id.slice(-10)}
                  {r.started_by ? ` · Started by ${r.started_by}` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {preview && (
          <>
            <h2>Review all {preview.rows.length} members</h2>
            <div className="mt-standardize-actions">
              <strong>{selected.size} members selected</strong>
              <button
                disabled={busy || disabled || !selected.size}
                onClick={() => void confirm()}
              >
                Rename {selected.size} members
              </button>
              <button
                disabled={busy || disabled || !selected.size}
                onClick={() => setSelected(new Set())}
              >
                Unselect all
              </button>
              <label>
                <input
                  type="checkbox"
                  checked={reviewOnly}
                  onChange={(e) => setReviewOnly(e.target.checked)}
                />
                Needs review only
              </label>
            </div>
            <ul className="mt-list">
              {preview.rows
                .filter((r) => !reviewOnly || r.needs_review)
                .map((r) => (
                  <li key={r.discord_id}>
                    <label className="mt-check">
                      <input
                        type="checkbox"
                        checked={selected.has(r.discord_id)}
                        disabled={!!r.skip_reason || busy || disabled}
                        onChange={(e) => {
                          const next = new Set(selected);
                          if (e.target.checked) next.add(r.discord_id);
                          else next.delete(r.discord_id);
                          setSelected(next);
                        }}
                      />
                      <strong>{r.name}</strong>
                    </label>
                    <p>
                      {r.old_nickname || "(no nickname)"} →{" "}
                      {r.new_nickname || "(no change)"}
                    </p>
                    {r.needs_review && (
                      <p>
                        Needs review: no recognized zone suffix; the complete
                        name was kept.
                      </p>
                    )}
                    {r.skip_reason && <p>Skipped: {r.skip_reason}</p>}
                  </li>
                ))}
            </ul>
          </>
        )}
        {run && (
          <>
            <h2>
              Standardize progress ·{" "}
              {run.state === "done"
                ? "Finished"
                : run.state === "stopped"
                  ? "Stopped"
                  : run.state === "stopping"
                    ? "Stopping after current member"
                    : "Working"}
            </h2>
            <p>
              Started by {run.started_by || "Unknown"}
              {run.stopped_by ? ` · Stopped by ${run.stopped_by}` : ""}
            </p>
            {["queued", "stopping"].includes(run.state) && (
              <button
                disabled={busy || disabled || run.state === "stopping"}
                onClick={() => void stopRun()}
              >
                Stop run
              </button>
            )}
            <p role="status">
              {run.rows.filter((r) => r.status === "done").length} changed ·{" "}
              {
                run.rows.filter(
                  (r) => r.status === "skipped" || r.status === "stopped",
                ).length
              }{" "}
              skipped or stopped ·{" "}
              {run.rows.filter((r) => r.status === "failed").length} failed ·{" "}
              {run.rows.filter((r) => r.status === "uncertain").length} need
              manual checking
            </p>
            <ul className="mt-list">
              {run.rows.map((r) => (
                <li key={r.discord_id}>
                  <strong>
                    {r.name || r.old_nickname || r.discord_id}
                    {r.new_nickname ? ` → ${r.new_nickname}` : ""}
                  </strong>
                  <p>
                    {r.status}: {r.message}
                  </p>
                </li>
              ))}
            </ul>
          </>
        )}
      </details>
    </section>
  );
}
