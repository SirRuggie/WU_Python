import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import LoadError from "../LoadError";
import { RefreshButton } from "../RefreshControl";
import type { ManagementSection } from "../serverManagement";

type Result = {
  status: string;
  message: string;
  result?: { details?: string };
};
type Detail = { data?: Result; error?: string; loading?: boolean };
const validRecord = (value: ManagementSection) =>
  value &&
  typeof value.id === "string" &&
  typeof value.label === "string" &&
  typeof value.endpoint === "string" &&
  /^\/manage\/return-batches\/[a-zA-Z0-9:_-]{1,200}$/.test(value.endpoint);

export default function ReturnReminderHistory({
  active,
  disabled,
  onOpen,
  onAccessLost,
  accessRevision = 0,
}: {
  accessRevision?: number;
  active: boolean;
  disabled: boolean;
  onOpen: (record: ManagementSection) => void;
  onAccessLost: (message: string) => void;
}) {
  const [records, setRecords] = useState<ManagementSection[]>([]);
  const [details, setDetails] = useState<Record<string, Detail>>({});
  const [loading, setLoading] = useState(false);
  const [moreLoading, setMoreLoading] = useState(false);
  const [error, setError] = useState("");
  const [visible, setVisible] = useState(5);
  const epoch = useRef(0);
  const live = useRef(false);
  const count = useRef(5);
  const heading = useRef<HTMLParagraphElement>(null);
  const opened = useRef("");
  const pending = useRef(new Set<string>());
  const current = (turn: number) => live.current && turn === epoch.current;
  const denied = (cause: unknown, turn: number) => {
    if (
      !(cause instanceof ApiError) ||
      ![401, 403].includes(cause.status) ||
      !current(turn)
    )
      return false;
    ++epoch.current;
    setRecords([]);
    setDetails({});
    setLoading(false);
    setMoreLoading(false);
    setError(cause.message);
    onAccessLost(cause.message);
    return true;
  };
  const loadDetails = async (rows: ManagementSection[], turn: number) => {
    await Promise.all(
      rows.map(async (record) => {
        const key = `${turn}:${record.id}`;
        if (!current(turn) || pending.current.has(key)) return;
        pending.current.add(key);
        setDetails((old) => ({
          ...old,
          [record.id]: { ...old[record.id], loading: true, error: "" },
        }));
        try {
          const value = await api<Result>(`${record.endpoint}/status`);
          if (
            typeof value?.status !== "string" ||
            typeof value.message !== "string" ||
            (value.result?.details !== undefined &&
              typeof value.result.details !== "string")
          )
            throw new Error("This action's result is unavailable.");
          if (current(turn))
            setDetails((old) => ({ ...old, [record.id]: { data: value } }));
        } catch (cause) {
          if (denied(cause, turn)) return;
          if (current(turn))
            setDetails((old) => ({
              ...old,
              [record.id]: {
                error:
                  cause instanceof Error
                    ? cause.message
                    : "Could not load this action.",
              },
            }));
        } finally {
          pending.current.delete(key);
        }
      }),
    );
  };
  const load = async () => {
    if (!live.current) return;
    const turn = ++epoch.current;
    setLoading(true);
    setMoreLoading(false);
    setError("");
    try {
      const response = await api<{ documents: ManagementSection[] }>(
        "/manage/return-batches",
      );
      if (
        !Array.isArray(response.documents) ||
        !response.documents.every(validRecord) ||
        new Set(response.documents.map((row) => row.id)).size !==
          response.documents.length
      )
        throw new Error("Return action history is unavailable.");
      if (!current(turn)) return;
      const rows = response.documents.slice(0, 20);
      setRecords(rows);
      setDetails({});
      if (opened.current && !rows.some((row) => row.id === opened.current))
        heading.current?.focus();
      await loadDetails(rows.slice(0, count.current), turn);
    } catch (cause) {
      if (denied(cause, turn)) return;
      if (current(turn))
        setError(
          cause instanceof Error ? cause.message : "Could not load history.",
        );
    } finally {
      if (current(turn)) setLoading(false);
    }
  };
  // Another protected Return read may lose access while this mounted panel is hidden.
  // Clear cached rows and abandon in-flight results without starting another request.
  useEffect(() => {
    if (!accessRevision) return;
    ++epoch.current;
    setRecords([]);
    setDetails({});
    setLoading(false);
    setMoreLoading(false);
    setError("");
  }, [accessRevision]);
  useEffect(() => {
    live.current = active;
    if (active) void load();
    else ++epoch.current;
    return () => {
      live.current = false;
      ++epoch.current;
    };
  }, [active]);
  const showMore = async () => {
    if (!live.current || loading || moreLoading || disabled) return;
    const turn = epoch.current;
    const next = Math.min(visible + 5, records.length);
    count.current = next;
    setVisible(next);
    setMoreLoading(true);
    try {
      await loadDetails(records.slice(visible, next), turn);
    } finally {
      if (current(turn)) setMoreLoading(false);
    }
  };
  return (
    <section className="return-history-panel">
      <div className="section-heading return-history-first-row">
        <p className="small" tabIndex={-1} ref={heading}>
          Latest 20 staff actions.
        </p>
        <RefreshButton
          label="Refresh return history"
          busy={loading || moreLoading}
          disabled={disabled || !active}
          onRefresh={load}
        />
      </div>
      <LoadError
        message={error}
        busy={loading}
        note={
          error && records.length
            ? "Showing the last loaded history."
            : undefined
        }
        onRetry={() => void load()}
      />
      {loading && !records.length && <p role="status">Loading history…</p>}
      {!loading && !error && !records.length && (
        <p>No group actions recorded.</p>
      )}
      <div className="return-history-list">
        {records.slice(0, visible).map((record) => {
          const detail = details[record.id];
          return (
            <article key={record.id}>
              <h3>{record.label}</h3>
              {detail?.loading && <p role="status">Loading result…</p>}
              {detail?.data && (
                <>
                  <p>
                    {detail.data.message.replace(
                      /\b1 need checking\b/g,
                      "1 needs checking",
                    )}
                  </p>
                  <p className="return-history-result">
                    {detail.data.result?.details ||
                      "Clan result details unavailable."}
                  </p>
                </>
              )}
              {detail?.error && (
                <LoadError
                  message={detail.error}
                  onRetry={() => void loadDetails([record], epoch.current)}
                />
              )}
              <button
                disabled={disabled || loading || moreLoading}
                onClick={() => {
                  opened.current = record.id;
                  onOpen(record);
                }}
              >
                View action details
              </button>
            </article>
          );
        })}
      </div>
      {visible < records.length && (
        <button
          disabled={disabled || loading || moreLoading}
          onClick={() => void showMore()}
        >
          Show more
        </button>
      )}
    </section>
  );
}
