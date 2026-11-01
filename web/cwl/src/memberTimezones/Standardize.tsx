import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { discordIdentityName } from "../DiscordIdentity";
import NicknameReview from "./NicknameReview";
import NicknameRun from "./NicknameRun";
import type { Change, Run, Member, RequestState } from "./types";
const interrupted =
  "Import stopped early. No nicknames changed. Press Import again to continue.";
export default function Standardize({
  disabled,
  onDenied,
  members = [],
  onBusy = () => {},
  onImported = () => {},
  onRefresh,
  refreshing = false,
}: {
  disabled: boolean;
  onDenied: () => void;
  members?: Member[];
  onBusy?: (busy: boolean) => void;
  onImported?: () => void;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  const [preview, setPreview] = useState<{
      token: string;
      rows: Change[];
    } | null>(null),
    [selected, setSelected] = useState<Set<string>>(new Set()),
    [run, setRun] = useState<Run | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [phase, setPhase] = useState(""),
    [past, setPast] = useState(false),
    [history, setHistory] = useState<
      { run_id: string; state: string; started_by?: string }[]
    >([]);
  const alive = useRef(true),
    generation = useRef(0),
    working = useRef(false),
    importId = useRef(crypto.randomUUID()),
    receipt = useRef<RequestState | null>(null),
    controller = useRef<AbortController | null>(null);
  const callbacks = useRef({ onBusy, onImported, onDenied });
  callbacks.current = { onBusy, onImported, onDenied };
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      generation.current++;
      controller.current?.abort();
      callbacks.current.onBusy(false);
    };
  }, []);
  function fail(cause: unknown) {
    if (!alive.current) return;
    if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
      setPreview(null);
      setRun(null);
      setHistory([]);
      callbacks.current.onDenied();
    } else
      setError(
        cause instanceof Error
          ? cause.message
          : "Nickname review is unavailable.",
      );
  }
  function start() {
    if (working.current || disabled) return false;
    working.current = true;
    setBusy(true);
    callbacks.current.onBusy(true);
    setError("");
    return true;
  }
  function finish() {
    working.current = false;
    if (alive.current) {
      setBusy(false);
      setPhase("");
      callbacks.current.onBusy(false);
    }
  }
  useEffect(() => {
    if (!past) return;
    let active = true;
    void api<{ runs: typeof history }>("/manage/member-timezones/runs")
      .then((r) => {
        if (active) setHistory(r.runs);
      })
      .catch((e) => {
        if (active) fail(e);
      });
    return () => {
      active = false;
    };
  }, [past]);
  useEffect(() => {
    if (!run || !["queued", "stopping"].includes(run.state)) return;
    let active = true,
      inflight = false;
    const id = run.run_id;
    const poll = async () => {
      if (
        !active ||
        inflight ||
        working.current ||
        document.visibilityState === "hidden"
      )
        return;
      inflight = true;
      const version = generation.current;
      try {
        const next = await api<Run>(
          `/manage/member-timezones/runs/${encodeURIComponent(id)}`,
        );
        if (active && version === generation.current) setRun(next);
      } catch (e) {
        if (active) fail(e);
      } finally {
        inflight = false;
      }
    };
    const timer = setInterval(() => void poll(), 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [run?.run_id, run?.state]);
  async function review() {
    if (!start()) return;
    const version = ++generation.current;
    const abort = new AbortController();
    controller.current = abort;
    setPreview(null);
    setRun(null);
    setPhase("Importing time zones…");
    try {
      if (
        receipt.current &&
        ["done", "failed", "uncertain", "stopped"].includes(
          receipt.current.status,
        )
      ) {
        importId.current = crypto.randomUUID();
        receipt.current = null;
      }
      let result = await api<RequestState>(
        "/manage/member-timezones/import",
        "POST",
        { request_id: importId.current },
        { signal: abort.signal },
      );
      receipt.current = result;
      while (["pending", "running"].includes(result.status)) {
        if (abort.signal.aborted) return;
        await new Promise<void>((resolve) => {
          const timer = setTimeout(done, 1000);
          function done() {
            clearTimeout(timer);
            abort.signal.removeEventListener("abort", done);
            resolve();
          }
          abort.signal.addEventListener("abort", done, { once: true });
        });
        if (abort.signal.aborted) return;
        if (document.visibilityState === "hidden") continue;
        result = await api<RequestState>(result.status_url, "GET", undefined, {
          signal: abort.signal,
        });
        receipt.current = result;
      }
      if (!alive.current || version !== generation.current) return;
      if (result.status !== "done") {
        setError(interrupted);
        return;
      }
      setPhase("Building review…");
      const next = await api<{ token: string; rows: Change[] }>(
        "/manage/member-timezones/preview",
        "POST",
        {},
        { signal: abort.signal },
      );
      if (!alive.current || version !== generation.current) return;
      setPreview(next);
      setSelected(
        new Set(
          next.rows
            .filter(
              (r) =>
                r.category === "will_change" &&
                !r.skip_reason &&
                !r.needs_review,
            )
            .map((r) => r.discord_id),
        ),
      );
      callbacks.current.onImported();
    } catch (e) {
      if (!abort.signal.aborted && version === generation.current) fail(e);
    } finally {
      finish();
    }
  }
  async function confirm() {
    if (!preview || !selected.size || !start()) return;
    const version = ++generation.current;
    try {
      const result = await api<{ run_id: string }>(
        "/manage/member-timezones/confirm",
        "POST",
        { token: preview.token, selected: [...selected] },
      );
      const next = await api<Run>(
        `/manage/member-timezones/runs/${encodeURIComponent(result.run_id)}`,
      );
      if (alive.current && version === generation.current) {
        setRun(next);
        setPreview(null);
      }
    } catch (e) {
      if (version === generation.current) fail(e);
    } finally {
      finish();
    }
  }
  async function openRun(id: string) {
    if (!start()) return;
    const version = ++generation.current;
    try {
      const next = await api<Run>(
        `/manage/member-timezones/runs/${encodeURIComponent(id)}`,
      );
      if (alive.current && version === generation.current) {
        setRun(next);
        setPreview(null);
      }
    } catch (e) {
      fail(e);
    } finally {
      finish();
    }
  }
  async function stop() {
    if (!run || !start()) return;
    const version = ++generation.current;
    try {
      await api(
        `/manage/member-timezones/runs/${encodeURIComponent(run.run_id)}/stop`,
        "POST",
        {},
      );
      const next = await api<Run>(
        `/manage/member-timezones/runs/${encodeURIComponent(run.run_id)}`,
      );
      if (alive.current && version === generation.current) setRun(next);
    } catch (e) {
      fail(e);
    } finally {
      finish();
    }
  }
  function close() {
    generation.current++;
    controller.current?.abort();
    setPreview(null);
    setRun(null);
    setError("");
  }
  return (
    <section className="mt-nickname-review">
      <div className="mt-review-entry">
        <button
          disabled={
            disabled ||
            busy ||
            (!!run && ["queued", "stopping"].includes(run.state))
          }
          onClick={() => void review()}
        >
          Review nicknames
        </button>
        {onRefresh && (
          <button disabled={busy || disabled || refreshing} onClick={onRefresh}>
            Refresh members
          </button>
        )}
        <button
          className="link-button"
          disabled={busy}
          onClick={() => setPast(!past)}
        >
          Past runs
        </button>
      </div>
      <p className="mt-review-help">
        Saves time zones from nicknames, then shows the changes. Nobody is
        renamed until you confirm.
      </p>
      {error && <p role="alert">{error}</p>}
      {busy && phase && <p role="status">{phase}</p>}
      {(busy || preview || run) && (
        <button disabled={busy && !phase} onClick={close}>
          Back to members
        </button>
      )}
      {past && (
        <label>
          Past runs
          <select
            disabled={busy || disabled}
            value={run?.run_id || ""}
            onChange={(e) => {
              if (e.target.value) void openRun(e.target.value);
            }}
          >
            <option value="">Choose a run</option>
            {history.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.state} · {r.run_id.slice(-10)}
                {r.started_by
                  ? ` · ${discordIdentityName(r.started_by, members.find((m) => m.discord_id === r.started_by)?.discord_profile, members.find((m) => m.discord_id === r.started_by)?.name) || "Discord member unavailable"}`
                  : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      {preview && (
        <NicknameReview
          rows={preview.rows}
          members={members}
          selected={selected}
          onSelect={setSelected}
          onConfirm={() => void confirm()}
          disabled={busy || disabled}
        />
      )}{" "}
      {run && (
        <NicknameRun
          run={run}
          members={members}
          disabled={busy || disabled}
          onStop={() => void stop()}
        />
      )}
    </section>
  );
}
