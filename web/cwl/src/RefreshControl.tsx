import { useEffect, useRef, useState } from "react";
import { Pause, Play, RefreshCw } from "lucide-react";
import { formatTime } from "./format";
import "./RefreshControl.css";

type Refresh = () => void | Promise<unknown>;

/** Record successful read completion, never a clock tick or an unsuccessful read. */
export function useRefreshTime(busy: boolean, loaded: boolean, error = "") {
  const [snapshot, setSnapshot] = useState<{
    busy: boolean;
    updatedAt: number | null;
  }>({ busy, updatedAt: null });
  if (snapshot.busy !== busy) {
    setSnapshot({
      busy,
      updatedAt:
        snapshot.busy && !busy && loaded && !error
          ? Date.now()
          : snapshot.updatedAt,
    });
  }
  return snapshot.updatedAt;
}

/** Shared row-level icon; the caller keeps the existing read and its placement. */
export function RefreshButton({
  busy,
  onRefresh,
  disabled = false,
  label = "Refresh",
}: {
  busy: boolean;
  onRefresh: Refresh;
  disabled?: boolean;
  label?: string;
}) {
  const inFlight = useRef(false);
  const [pending, setPending] = useState(false);
  const working = busy || pending;
  return (
    <button
      type="button"
      className="refresh-icon-button"
      aria-label={label}
      title={label}
      aria-busy={working || undefined}
      disabled={working || disabled}
      onClick={() => {
        if (busy || disabled || inFlight.current) return;
        inFlight.current = true;
        setPending(true);
        const finish = () => {
          inFlight.current = false;
          setPending(false);
        };
        try {
          Promise.resolve(onRefresh()).then(finish, finish);
        } catch (error) {
          finish();
          throw error;
        }
      }}
    >
      <RefreshCw
        size={18}
        aria-hidden="true"
        className={working ? "is-refreshing" : undefined}
      />
    </button>
  );
}

export type RefreshControlProps = {
  updatedAt: Parameters<typeof formatTime>[0];
  busy: boolean;
  onRefresh: Refresh;
  intervalSeconds?: number;
  paused?: boolean;
  onPauseChange?: (paused: boolean) => void;
  disabled?: boolean;
  /** The same read's LoadError owns Try again while its error is visible. */
  showRefresh?: boolean;
};

export default function RefreshControl({
  updatedAt,
  busy,
  onRefresh,
  intervalSeconds,
  paused = false,
  onPauseChange,
  disabled = false,
  showRefresh = true,
}: RefreshControlProps) {
  const previous = useRef(busy);
  const announce = previous.current && !busy && showRefresh;
  useEffect(() => {
    previous.current = busy;
  }, [busy]);
  const time = formatTime(updatedAt);
  const status = updatedAt == null ? "Not updated" : `Updated ${time}`;
  const automatic =
    intervalSeconds !== undefined && onPauseChange !== undefined;
  const interval = automatic
    ? paused
      ? " · paused"
      : ` · every ${intervalSeconds} s`
    : "";
  return (
    <div className="refresh-control">
      <span
        className="refresh-control-status"
        role={announce ? "status" : undefined}
        aria-label={status + interval}
      >
        {updatedAt == null ? (
          status
        ) : (
          <>
            <span className="refresh-status-prefix">Updated </span>
            {time}
          </>
        )}
        <span className="refresh-interval">{interval}</span>
      </span>
      {showRefresh && (
        <RefreshButton busy={busy} disabled={disabled} onRefresh={onRefresh} />
      )}
      {automatic && (
        <button
          type="button"
          className="refresh-icon-button"
          aria-label={
            paused ? "Resume automatic refresh" : "Pause automatic refresh"
          }
          title={
            paused ? "Resume automatic refresh" : "Pause automatic refresh"
          }
          disabled={disabled}
          onClick={() => onPauseChange(!paused)}
        >
          {paused ? (
            <Play size={18} aria-hidden="true" />
          ) : (
            <Pause size={18} aria-hidden="true" />
          )}
        </button>
      )}
    </div>
  );
}
