import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, ApiError } from "./api";
import "./MemberActivityHistory.css";
import MemberEventRow, { type MemberEvent } from "./MemberEventRow";

type Response = { events: MemberEvent[]; next_cursor: string | null };
type EventType =
  | "all"
  | "join"
  | "leave"
  | "kick"
  | "ban"
  | "unban"
  | "timeout_add"
  | "timeout_remove"
  | "member_update"
  | "roles_added"
  | "roles_removed"
  | "invite_use";
type Filters = { query: string; type: EventType; from: string; to: string };

export default function MemberActivityHistory({
  active = true,
  onViewMember,
}: {
  active?: boolean;
  onViewMember?: (userId: string) => void;
}) {
  const [rows, setRows] = useState<MemberEvent[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [type, setType] = useState<EventType>("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loadedAt, setLoadedAt] = useState("");
  const [filters, setFilters] = useState<Filters>({
    query: "",
    type: "all",
    from: "",
    to: "",
  });
  const request = useRef(0);

  const load = useCallback(
    async (pageCursor: string | null, replace = true) => {
      const id = ++request.current;
      setLoading(true);
      setError("");
      const params = new URLSearchParams({ limit: "50" });
      if (filters.query) params.set("q", filters.query);
      if (filters.type !== "all") params.set("type", filters.type);
      if (filters.from) params.set("from", filters.from);
      if (filters.to) params.set("to", filters.to);
      if (pageCursor) params.set("before", pageCursor);

      try {
        const result = await api<Response>(`/manage/member-events?${params}`);
        if (request.current !== id) return;
        setRows((current) =>
          replace ? result.events : [...current, ...result.events],
        );
        setNextCursor(result.next_cursor || null);
        setLoadedAt(new Date().toISOString());
      } catch (cause) {
        if (request.current !== id) return;
        if (
          cause instanceof ApiError &&
          (cause.status === 401 || cause.status === 403)
        ) {
          setRows([]);
          setNextCursor(null);
          setError(
            "Your staff access has changed. Sign in again or ask an administrator to restore access.",
          );
        } else {
          setError(
            cause instanceof Error
              ? cause.message
              : "Could not load member activity. Try again.",
          );
        }
      } finally {
        if (request.current === id) setLoading(false);
      }
    },
    [filters],
  );

  useEffect(() => {
    if (!active) {
      request.current += 1;
      setLoading(false);
      return;
    }
    void load(null);
    return () => {
      request.current += 1;
    };
  }, [active, load]);

  const applyFilters = (event: FormEvent) => {
    event.preventDefault();
    request.current += 1;
    setFilters({ query: search.trim(), type, from, to });
    setRows([]);
  };

  const clearFilters = () => {
    request.current += 1;
    setSearch("");
    setType("all");
    setFrom("");
    setTo("");
    setFilters({ query: "", type: "all", from: "", to: "" });
    setRows([]);
  };

  const showNext = () => {
    if (nextCursor) void load(nextCursor, false);
  };
  const noMatches = !loading && !error && rows.length === 0;

  return (
    <section
      className="member-activity"
      aria-labelledby="member-activity-title"
    >
      <header className="member-activity-heading">
        <div>
          <h2 id="member-activity-title">Activity history</h2>
          <p>
            Recent joins, leaves, kicks, bans, timeouts, role changes and
            profile changes. A kick or ban can also create a separate leave
            event.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load(null)}
          disabled={loading}
        >
          Refresh
        </button>
      </header>

      <form className="member-activity-filters" onSubmit={applyFilters}>
        <label className="member-activity-search">
          Search name or Discord ID
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Name or Discord ID"
          />
        </label>
        <label>
          Activity
          <select
            value={type}
            onChange={(event) => setType(event.target.value as EventType)}
          >
            <option value="all">All activity</option>
            <option value="join">Joins</option>
            <option value="leave">Leaves</option>
            <option value="kick">Kicks</option>
            <option value="ban">Bans</option>
            <option value="unban">Unbans</option>
            <option value="timeout_add">Timeouts</option>
            <option value="timeout_remove">Timeout removals</option>
            <option value="member_update">Profile changes</option>
            <option value="roles_added">Roles added</option>
            <option value="roles_removed">Roles removed</option>
            <option value="invite_use">Invite uses</option>
          </select>
        </label>
        <details className="member-activity-date-range">
          <summary>Date range</summary>
          <div className="member-activity-date-fields">
            <label>
              From (UTC)
              <input
                type="date"
                value={from}
                onChange={(event) => setFrom(event.target.value)}
              />
            </label>
            <label>
              To (UTC)
              <input
                type="date"
                value={to}
                onChange={(event) => setTo(event.target.value)}
              />
            </label>
            <small className="member-activity-date-help">
              Dates use UTC. Event times below use your local timezone.
            </small>
          </div>
        </details>
        <button type="submit">Apply filters</button>
      </form>

      {error && (
        <div className="member-activity-error" role="alert">
          {error}
          <button
            type="button"
            disabled={loading}
            onClick={() => void load(null)}
          >
            Try again
          </button>
        </div>
      )}
      {error && rows.length > 0 && (
        <p className="member-activity-loaded">
          Showing the last loaded activity.
        </p>
      )}
      {loadedAt && !error && (
        <p className="member-activity-loaded">
          Updated{" "}
          <time dateTime={loadedAt}>
            {new Date(loadedAt).toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
            })}
          </time>
        </p>
      )}
      {loading && (
        <p role="status" className="member-activity-status">
          {rows.length ? "Updating activity…" : "Loading member activity…"}
        </p>
      )}
      {noMatches && (
        <div className="member-activity-empty">
          <p>
            {filters.query ||
            filters.type !== "all" ||
            filters.from ||
            filters.to
              ? "No activity matches these filters."
              : "No member activity has been recorded yet."}
          </p>
          {(filters.query ||
            filters.type !== "all" ||
            filters.from ||
            filters.to) && (
            <button type="button" onClick={clearFilters}>
              Clear filters
            </button>
          )}
        </div>
      )}

      {rows.length > 0 && (
        <>
          <ul
            className="member-activity-list"
            aria-label="Member join and leave history"
          >
            {rows.map((item) => (
              <MemberEventRow
                key={item.id}
                item={item}
                onViewMember={onViewMember}
              />
            ))}
          </ul>
          {nextCursor && (
            <div className="member-activity-more">
              <button type="button" onClick={showNext} disabled={loading}>
                Load older activity
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
