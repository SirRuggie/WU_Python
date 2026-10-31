import { useContext, useEffect, useState } from "react";
import { api } from "./api";
import { DashboardPermissions } from "./DashboardPermissions";
import "./VisitorSummary.css";

type Counts = { total: number; staff: number; members: number };
type Visits = {
  today: string;
  timezone: string;
  windows: Record<string, Counts>;
  series: (Counts & { day: string })[];
};

export default function VisitorSummary({ refresh = 0 }: { refresh?: number }) {
  const owner = useContext(DashboardPermissions)?.owner === true;
  const [data, setData] = useState<Visits | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!owner) return;
    let active = true;
    setError("");
    void api<Visits>("/manage/visitors").then(
      (result) => { if (active) setData(result); },
      () => { if (active) setError("Visitor counts could not be loaded."); },
    );
    return () => { active = false; };
  }, [owner, refresh, retry]);
  if (!owner) return null;
  const peak = Math.max(1, ...(data?.series.map((day) => day.total) ?? []));
  const points = data?.series.map((day, index) => `${4 + index * 10},${56 - day.total / peak * 48}`).join(" ");
  return (
    <section className="visitor-summary" aria-labelledby="visitor-title">
      <h2 id="visitor-title">Visitors</h2>
      {error ? <p role="alert">{error} <button onClick={() => setRetry((n) => n + 1)}>Try again</button></p> : null}
      {!data && !error ? <p role="status">Loading visitor counts…</p> : null}
      {data ? <>
        <dl className="visitor-counts">
          {[["1", "Today"], ["7", "7 days"], ["30", "30 days"]].map(([key, label]) => {
            const counts = data.windows[key];
            return <div key={key}><dt>{label}</dt><dd><strong>{counts.total}</strong><span>{counts.members} {counts.members === 1 ? "member" : "members"} · {counts.staff} staff</span></dd></div>;
          })}
        </dl>
        <svg viewBox="0 0 298 64" role="img" aria-label="Unique dashboard visitors each day for the last 30 days">
          <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
        <p className="visitor-note">Unique people · New York days · Staff includes anyone recorded as staff during the period.</p>
        <details><summary>Daily counts</summary><table><caption>Last 30 days</caption><thead><tr><th>Date</th><th>Members</th><th>Staff</th><th>Total</th></tr></thead><tbody>{data.series.map((day) => <tr key={day.day}><th scope="row">{day.day}</th><td>{day.members}</td><td>{day.staff}</td><td>{day.total}</td></tr>)}</tbody></table></details>
      </> : null}
    </section>
  );
}
