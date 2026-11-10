import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, ApiError } from "./api";
import {
  currentWarStateLabel,
  displayTrackingStatus,
  trackingIssues,
  trackingStatusLabel,
  trackingSummary,
  type ClanTracking,
  type TrackingResponse,
} from "./strikeTracking";

const when = (value?: string | null) => {
  if (!value) return "Not yet";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unavailable" : date.toLocaleString();
};
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Could not load tracking status.";

export default function StrikeTrackingStatus({
  canRetry,
  compact = false,
  portalTarget = null,
}: {
  canRetry: boolean;
  compact?: boolean;
  portalTarget?: HTMLElement | null;
}) {
  const [open, setOpen] = useState(false);
  const disclosureRef = useRef<HTMLDetailsElement>(null);
  const [clans, setClans] = useState<ClanTracking[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retryError, setRetryError] = useState("");
  const [busyClan, setBusyClan] = useState("");
  const request = useRef(0);
  const mounted = useRef(true);
  const pending = useRef<AbortController | null>(null);
  const lastRead = useRef<number | null>(null);

  const load = async (force = false) => {
    if (pending.current && !force) return;
    const previous = pending.current;
    const controller = new AbortController();
    pending.current = controller;
    previous?.abort();
    lastRead.current = Date.now();
    const current = ++request.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const data = await Promise.race([
        api<TrackingResponse>("/strikes/tracking", "GET", undefined, {
          signal: controller.signal,
        }),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => {
            controller.abort();
            reject(
              new Error("Tracking check timed out. Retry to check again."),
            );
          }, 10_000);
        }),
      ]);
      if (mounted.current && current === request.current) {
        setClans(data.clans || []);
        setError("");
      }
    } catch (cause) {
      if (mounted.current && current === request.current) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          setClans([]);
        setError(message(cause));
      }
    } finally {
      clearTimeout(timer);
      if (current === request.current) pending.current = null;
      if (mounted.current && current === request.current) setLoading(false);
    }
  };

  useEffect(() => {
    mounted.current = true;
    void load();
    const refreshVisible = () => {
      if (document.visibilityState === "hidden") return;
      if (lastRead.current !== null && Date.now() - lastRead.current < 30_000)
        return;
      void load();
    };
    const timer = window.setInterval(() => {
      // Scheduled ticks may arrive a millisecond early; throttle events, not the interval.
      if (document.visibilityState !== "hidden") void load();
    }, 30_000);
    document.addEventListener("visibilitychange", refreshVisible);
    window.addEventListener("focus", refreshVisible);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshVisible);
      window.removeEventListener("focus", refreshVisible);
    };
  }, []);

  const retry = async (clanTag: string) => {
    setBusyClan(clanTag);
    setRetryError("");
    try {
      await api("/strikes/tracking/retry", "POST", { clan_tag: clanTag });
      if (!mounted.current) return;
      setClans((current) =>
        current.map((item) =>
          item.clan_tag === clanTag ? { ...item, retry_pending: true } : item,
        ),
      );
      await load(true);
    } catch (cause) {
      if (mounted.current) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          setClans([]);
        setRetryError(message(cause));
      }
    } finally {
      if (mounted.current) setBusyClan("");
    }
  };

  const summary = trackingSummary(clans);
  // Idle and healthy clans need no review; compared as strings so this compiles before idle is typed.
  const review = clans.filter(
    (item) => !["healthy", "idle"].includes(displayTrackingStatus(item)),
  ).length;
  const compactLabel = review
    ? `${review} ${review === 1 ? "clan needs" : "clans need"} review ›`
    : "All clans on track";
  const tone = error ? "warning" : summary.tone;
  // A native toggle may still be queued when the portal target changes.
  const disclosureOpen = disclosureRef.current?.open ?? open;
  const disclosure = (
    <details
      className={`card strikes-tracking ${tone}`}
      ref={disclosureRef}
      open={disclosureOpen}
      onToggle={(event) => {
        if (event.currentTarget === disclosureRef.current)
          setOpen(event.currentTarget.open);
      }}
    >
      <summary
        className={
          compact
            ? `strikes-tracking-link${!loading && !error && review ? " review" : ""}`
            : undefined
        }
      >
        {!compact && <span>Tracking</span>}
        <strong>
          {loading
            ? "Checking…"
            : error
              ? "Status unavailable"
              : compact
                ? compactLabel
                : summary.label}
        </strong>
      </summary>
      <div className="strikes-tracking-body">
        {error && (
          <div className="notice error" role="alert">
            {error}
            <button type="button" onClick={() => void load(true)}>
              Retry
            </button>
          </div>
        )}
        {retryError && (
          <div className="notice error" role="alert">
            {retryError}
          </div>
        )}
        {!loading && !error && clans.length === 0 && <p>No clan checks yet.</p>}
        {!error &&
          clans.map((item) => {
            const status = displayTrackingStatus(item);
            return (
              <div className="strikes-tracking-clan" key={item.clan_tag}>
                <div className="strikes-tracking-clan-heading">
                  <strong>{item.clan_name || item.clan_tag}</strong>
                  <span className={`strikes-tracking-state ${status}`}>
                    {trackingStatusLabel(status)}
                  </span>
                </div>
                <div className="strikes-tracking-facts">
                  <small>
                    Last war recorded{" "}
                    <strong>{when(item.latest_recorded_war_at)}</strong>
                  </small>
                  <small>
                    Current war{" "}
                    <strong>
                      {currentWarStateLabel(item.current_war_state)}
                    </strong>
                  </small>
                </div>
                <small>
                  Checked {when(item.last_checked_at)} · Last successful{" "}
                  {when(item.last_success_at)}
                </small>
                {item.deferred_accounts || item.skipped_wars ? (
                  <small>{trackingIssues(item)}</small>
                ) : null}
                {item.error && (
                  <small className="strikes-tracking-error">{item.error}</small>
                )}
                {canRetry && status !== "healthy" && (
                  <button
                    aria-busy={
                      (!item.retry_pending && busyClan === item.clan_tag) ||
                      undefined
                    }
                    type="button"
                    disabled={!!busyClan || item.retry_pending}
                    onClick={() => void retry(item.clan_tag)}
                  >
                    {item.retry_pending
                      ? "Retry queued"
                      : busyClan === item.clan_tag
                        ? "Queuing…"
                        : "Retry"}
                  </button>
                )}
              </div>
            );
          })}
      </div>
    </details>
  );
  return portalTarget ? createPortal(disclosure, portalTarget) : disclosure;
}
