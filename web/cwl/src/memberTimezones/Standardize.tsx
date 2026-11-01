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
    [history, setHistory] = useState<{ run_id: string; state: string }[]>([]);
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
    api<{ runs: { run_id: string; state: string }[] }>(
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
    if (!open || !run || run.state === "done") return;
    let cancelled = false,
      inflight = false;
    const id = run.run_id;
    const load = async () => {
      if (cancelled || inflight || document.visibilityState === "hidden")
        return;
      inflight = true;
      try {
        const result = await api<Run>(
          `/manage/member-timezones/runs/${encodeURIComponent(id)}`,
        );
        if (!cancelled) setRun(result);
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
          unchanged. The bot works one member at a time. A stopped run resumes
          unattempted members; uncertain changes require manual review and are
          never repeated automatically.
        </p>
        <button
          disabled={busy || disabled || run?.state === "queued"}
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
                </option>
              ))}
            </select>
          </label>
        )}
        {preview && (
          <>
            <h2>Review all {preview.rows.length} members</h2>
            <ul className="mt-list">
              {preview.rows.map((r) => (
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
                      Needs review: no recognized zone suffix; the complete name
                      was kept.
                    </p>
                  )}
                  {r.skip_reason && <p>Skipped: {r.skip_reason}</p>}
                </li>
              ))}
            </ul>
            <button
              disabled={busy || disabled || !selected.size}
              onClick={() => void confirm()}
            >
              Confirm {selected.size} nickname changes
            </button>
          </>
        )}
        {run && (
          <>
            <h2>
              Standardize progress ·{" "}
              {run.state === "done" ? "Finished" : "Working"}
            </h2>
            <p role="status">
              {run.rows.filter((r) => r.status === "done").length} saved ·{" "}
              {run.rows.filter((r) => r.status === "failed").length} failed ·{" "}
              {run.rows.filter((r) => r.status === "uncertain").length} need
              manual checking
            </p>
            <ul className="mt-list">
              {run.rows.map((r) => (
                <li key={r.discord_id}>
                  <strong>
                    {r.old_nickname || r.discord_id} → {r.new_nickname}
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
