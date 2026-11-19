import EmptyState from "./EmptyState";
import DashboardLink from "./DashboardLink";
import { dashboardPath } from "./dashboardHistory";
import RefreshControl from "./RefreshControl";
import { formatDateTime } from "./format";
import LoadError from "./LoadError";
import CwlPageHeader from "./CwlPageHeader";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { seasonMonthLabel } from "./seasonLabels";
import VisitorSummary from "./VisitorSummary";
import DashboardIcon from "./DashboardIcon";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Season } from "./api";
import {
  dashboardViews,
  navigationLabel,
  type DashboardView,
} from "./SidebarNavigation";
import "./StaffOverview.css";
type Snapshot = {
  checked_at: number;
  seasons: { id: number; label: string; signed_up: number; unplaced: number }[];
  tickets: { open: number; url: string | null } | null;
  failures_count: number;
  failures: {
    id: string;
    action: string;
    status: string;
    at: number;
    destination: DashboardView;
  }[];
  warnings: string[];
  areas: DashboardView[];
};
export default function StaffOverview({
  onNavigate,
  seasons = [],
}: {
  onNavigate: (view: DashboardView, season?: string) => void;
  seasons?: readonly Season[];
}) {
  const [data, setData] = useState<Snapshot | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [paused, setPaused] = useState(false),
    [refresh, setRefresh] = useState(0);
  const refreshRead = useRef<() => void>(() => {});
  useEffect(() => {
    let active = true,
      inflight = false;
    async function load() {
      if (inflight) return;
      inflight = true;
      setBusy(true);
      try {
        const next = await api<Snapshot>("/manage/staff-overview");
        if (active) {
          setData(next);
          setError("");
        }
      } catch (e) {
        if (active) {
          if (e instanceof ApiError && [401, 403].includes(e.status))
            setData(null);
          setError(
            e instanceof Error
              ? e.message
              : "Could not refresh staff overview.",
          );
        }
      } finally {
        inflight = false;
        if (active) setBusy(false);
      }
    }
    refreshRead.current = () => {
      void load();
    };
    void load();
    return () => {
      active = false;
      refreshRead.current = () => {};
    };
  }, [refresh]);
  useEffect(() => {
    if (paused) return;
    const timer = setInterval(() => {
      if (!document.hidden) refreshRead.current();
    }, 30000);
    return () => clearInterval(timer);
  }, [paused]);
  return (
    <section className="staff-overview">
      <CwlPageHeader
        title={<h1>Staff overview</h1>}
        description="What needs attention across your areas."
      >
        <RefreshControl
          updatedAt={data ? data.checked_at * 1000 : null}
          busy={busy}
          onRefresh={() => setRefresh((v) => v + 1)}
          intervalSeconds={30}
          paused={paused}
          onPauseChange={(next) => {
            setPaused(next);
            if (!next) refreshRead.current();
          }}
          showRefresh={!error}
        />
      </CwlPageHeader>
      <VisitorSummary refresh={refresh} />
      <LoadError
        message={error}
        note={data ? "Showing the last successful update." : undefined}
        onRetry={() => setRefresh((v) => v + 1)}
        busy={busy}
      />
      {data && (
        <>
          <div className="staff-overview-cards">
            {data.areas.includes("roster") && (
              <article className="card">
                <h2>
                  <DashboardIcon name="roster" /> CWL placement
                </h2>
                {data.seasons.length ? (
                  data.seasons.map((season) => (
                    <div className="staff-overview-row" key={season.id}>
                      <div>
                        <strong>
                          {seasonMonthLabel(
                            seasons.find((item) => item.id === season.id) ||
                              season,
                          )}
                        </strong>
                        <p>
                          <b>{season.unplaced}</b> need placement ·{" "}
                          {season.signed_up} signed up
                        </p>
                      </div>
                      <DashboardLink
                        className="button"
                        href={dashboardPath({
                          view: "roster",
                          season: String(season.id),
                        })}
                        onNavigate={() =>
                          onNavigate("roster", String(season.id))
                        }
                      >
                        Open roster <ArrowRight size={16} aria-hidden="true" />
                      </DashboardLink>
                    </div>
                  ))
                ) : (
                  <EmptyState
                    title="No active CWL seasons"
                    line="Active seasons will appear here."
                  />
                )}
              </article>
            )}
            {data.tickets && (
              <article className="card">
                <h2>
                  <DashboardIcon name="ticket" /> Tickets
                </h2>
                <p className="staff-overview-count">{data.tickets.open}</p>
                <p>Open tickets in the current Discord ticket system.</p>
                {data.tickets.url ? (
                  <a
                    className="button"
                    href={data.tickets.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open ticket console{" "}
                    <ArrowUpRight size={16} aria-hidden="true" />
                  </a>
                ) : (
                  <p>
                    Use the ticket console in Discord. Its dashboard link is not
                    configured.
                  </p>
                )}
              </article>
            )}
            <article className="card">
              <h2>
                <DashboardIcon name="warning" /> Recent failed actions
              </h2>
              <p className="staff-overview-count">{data.failures_count}</p>
              <p>
                Your failed or unconfirmed actions in the last 7 days. A later
                retry may have succeeded.
              </p>
              {data.failures.length ? (
                <>
                  <div>
                    {data.failures.map((f) => (
                      <div className="staff-overview-row" key={f.id}>
                        <div>
                          <strong>
                            {navigationLabel(f.destination)} · {f.action}
                          </strong>
                          <p>
                            {f.status === "uncertain"
                              ? "Unconfirmed — check Discord first"
                              : "Failed"}{" "}
                            · {formatDateTime(new Date(f.at * 1000))}
                          </p>
                        </div>
                        {dashboardViews.includes(f.destination) &&
                          navigationLabel(f.destination) && (
                            <DashboardLink
                              className="button"
                              href={dashboardPath({
                                view: f.destination,
                                season: "",
                              })}
                              onNavigate={() => onNavigate(f.destination)}
                            >
                              Review area{" "}
                              <ArrowRight size={16} aria-hidden="true" />
                            </DashboardLink>
                          )}
                      </div>
                    ))}
                  </div>
                  {data.failures_count > 5 && (
                    <p className="small">Showing the latest 5.</p>
                  )}
                </>
              ) : (
                <EmptyState
                  title="No recent failed actions"
                  line="There are no failures to review."
                />
              )}
            </article>
          </div>
          {data.warnings.map((w) => (
            <p className="small" key={w}>
              {w}
            </p>
          ))}
          <section className="card">
            <h2>Your tools</h2>
            <div className="staff-overview-shortcuts">
              {[...new Set(data.areas)]
                .filter(
                  (area) =>
                    dashboardViews.includes(area) && navigationLabel(area),
                )
                .map((area) => (
                  <DashboardLink
                    key={area}
                    href={dashboardPath({ view: area, season: "" })}
                    onNavigate={() => onNavigate(area)}
                  >
                    {navigationLabel(area)} →
                  </DashboardLink>
                ))}
            </div>
          </section>
        </>
      )}
    </section>
  );
}
