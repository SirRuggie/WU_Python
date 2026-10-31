import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import { api, ApiError } from "./api";
import { compactWeight, enteredWeight } from "./replacementView";
import type { ViewMemory } from "./strikeViewMemory";
import {
  activityChips,
  activityCounts,
  activityFilterQuery,
  activitySorts,
  activityStatusLabels,
  parseActivityFilters,
  visibleActivityAccounts,
  type ActivityAccount,
  type ActivityFilters,
  type ActivitySort,
  type ActivityStatus,
} from "./strikeActivityView";
import "./StrikeActivityRoster.css";

type Response = {
  accounts: ActivityAccount[];
  clans: { tag: string; name: string }[];
  weight_warning?: string;
  identity_warning?: string;
  activity_warning?: string;
};
const sortNames: Record<ActivitySort, string> = {
  status: "Status",
  quiet: "Quiet days",
  strikes: "Strikes",
  weight: "Weight",
  th: "Town hall",
  missed: "Missed attacks",
  name: "Name",
  priority: "Priority",
};
const toggle = <T,>(values: T[], value: T) =>
  values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];

export default function StrikeActivityRoster({
  state,
  markedDefault = false,
  reload = 0,
  memory,
  headingRef,
  focusTag,
  onRestored,
  onState,
  onChoose,
  onDenied,
}: {
  state?: string;
  markedDefault?: boolean;
  reload?: number;
  memory?: ViewMemory;
  headingRef?: RefObject<HTMLHeadingElement | null>;
  focusTag?: string | null;
  onRestored?: () => void;
  onState?: (state: string, push: boolean) => void;
  onChoose: (account: ActivityAccount) => void;
  onDenied?: () => void;
}) {
  const [local, setLocal] = useState(() =>
    parseActivityFilters(state ?? window.location.search, markedDefault),
  );
  const filters = useMemo(
    () =>
      state === undefined ? local : parseActivityFilters(state, markedDefault),
    [state, local, markedDefault],
  );
  const [data, setData] = useState<Response>({ accounts: [], clans: [] });
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [loadedAt, setLoadedAt] = useState("");
  const [tools, setTools] = useState(false);
  const request = useRef(0),
    pending = useRef(false),
    restored = useRef(false);
  const callbacks = useRef({ onDenied, onRestored });
  callbacks.current = { onDenied, onRestored };
  const read = useCallback(async () => {
    if (pending.current) return;
    const current = ++request.current;
    pending.current = true;
    setLoading(true);
    setError("");
    try {
      const result = await api<Response>("/strikes/accounts?activity=true");
      if (!Array.isArray(result.accounts) || !Array.isArray(result.clans))
        throw new Error(
          "Family activity response is incomplete. Refresh to try again.",
        );
      if (current !== request.current) return;
      setData(result);
      setLoadedAt(
        new Date().toLocaleTimeString([], {
          hour: "numeric",
          minute: "2-digit",
        }),
      );
    } catch (cause) {
      if (current !== request.current) return;
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
        setData({ accounts: [], clans: [] });
        callbacks.current.onDenied?.();
      }
      setError(
        cause instanceof Error
          ? cause.message
          : "Activity could not be loaded. Try again.",
      );
    } finally {
      if (current === request.current) {
        pending.current = false;
        setLoading(false);
      }
    }
  }, []);
  useEffect(() => {
    void read();
    return () => {
      request.current++;
      pending.current = false;
    };
  }, [read, reload]);
  const visible = useMemo(
    () => visibleActivityAccounts(data.accounts, filters),
    [data.accounts, filters],
  );
  const counts = activityCounts(visible),
    lastPage = Math.max(0, Math.ceil(visible.length / 25) - 1),
    page = Math.min(filters.page, lastPage);
  const rows = visible.slice(page * 25, (page + 1) * 25);
  useEffect(() => {
    if (loading || restored.current) return;
    const frame = requestAnimationFrame(() => {
      if (focusTag) {
        const button = document.querySelector<HTMLButtonElement>(
          `[data-strike-player="${CSS.escape(focusTag)}"]`,
        );
        (button || headingRef?.current)?.focus({ preventScroll: true });
        window.scrollTo(0, Number(memory?.get("activityScroll") || 0));
        callbacks.current.onRestored?.();
      }
      restored.current = true;
    });
    return () => cancelAnimationFrame(frame);
  }, [loading, focusTag, headingRef, memory, rows.length]);
  function change(patch: Partial<ActivityFilters>, push = true) {
    const next = {
      ...filters,
      ...patch,
      page: "page" in patch ? patch.page! : 0,
    };
    setLocal(next);
    if (onState) onState(activityFilterQuery(next), push);
    else {
      const url = new URL(window.location.href);
      for (const key of [
        "q",
        "clans",
        "status",
        "marked",
        "low",
        "strikes",
        "th",
        "left",
        "sort",
        "page",
      ])
        url.searchParams.delete(key);
      new URLSearchParams(activityFilterQuery(next)).forEach((value, key) =>
        url.searchParams.set(key, value),
      );
      history.replaceState(history.state, "", url.pathname + url.search);
    }
  }
  function choose(row: ActivityAccount) {
    memory?.set("activityScroll", window.scrollY);
    onChoose(row);
  }
  const halls = [
    ...new Set(
      data.accounts
        .map((row) => row.town_hall)
        .filter((value): value is number => !!value),
    ),
  ].sort((a, b) => b - a);
  return (
    <section
      className="strike-activity-roster"
      aria-label="Family activity overview"
    >
      <div className="strike-activity-toolbar">
        <label>
          Find account or member
          <input
            type="search"
            value={filters.query}
            maxLength={80}
            placeholder="Name, tag or Discord member"
            onChange={(event) => change({ query: event.target.value }, false)}
          />
        </label>
        <label>
          Sort
          <select
            value={filters.sort}
            onChange={(event) =>
              change({ sort: event.target.value as ActivitySort })
            }
          >
            {activitySorts.map((value) => (
              <option key={value} value={value}>
                {sortNames[value]}
              </option>
            ))}
          </select>
        </label>
        <button disabled={loading} onClick={() => void read()}>
          {loading ? "Refreshing…" : "Refresh activity"}
        </button>
      </div>
      <div className="strike-activity-filters">
        <details className="strike-activity-clans">
          <summary>
            Clans
            {filters.clans.length
              ? ` (${filters.clans.length} selected)`
              : " · all"}
          </summary>
          <fieldset>
            <legend>Show clans</legend>
            {data.clans.map((clan) => (
              <label key={clan.tag}>
                <input
                  type="checkbox"
                  checked={filters.clans.includes(clan.tag)}
                  onChange={() =>
                    change({ clans: toggle(filters.clans, clan.tag) })
                  }
                />
                {clan.name}
              </label>
            ))}
            <button onClick={() => change({ clans: [] })}>All clans</button>
          </fieldset>
        </details>

        <label>
          <input
            type="checkbox"
            checked={filters.marked}
            onChange={(event) => change({ marked: event.target.checked })}
          />
          Marked for replacement
        </label>
        {filters.marked && (
          <label>
            <input
              type="checkbox"
              checked={filters.includeLow}
              onChange={(event) => change({ includeLow: event.target.checked })}
            />
            Include 1–2 strikes
          </label>
        )}
        <details>
          <summary>
            More filters
            {filters.onlyStrikes ||
            filters.statuses.length ||
            filters.townHalls.length ||
            filters.left !== "all"
              ? " · applied"
              : ""}
          </summary>
          <div className="strike-activity-more">
            <fieldset className="strike-activity-status">
              <legend>Status</legend>
              {(["risk", "watch", "active"] as ActivityStatus[]).map(
                (value) => (
                  <label key={value}>
                    <input
                      type="checkbox"
                      checked={filters.statuses.includes(value)}
                      onChange={() =>
                        change({ statuses: toggle(filters.statuses, value) })
                      }
                    />
                    {activityStatusLabels[value]}
                  </label>
                ),
              )}
            </fieldset>
            <label>
              <input
                type="checkbox"
                checked={filters.onlyStrikes}
                onChange={(event) =>
                  change({ onlyStrikes: event.target.checked })
                }
              />
              Has active strikes
            </label>
            <label>
              Membership
              <select
                value={filters.left}
                onChange={(event) =>
                  change({
                    left: event.target.value as ActivityFilters["left"],
                  })
                }
              >
                <option value="all">Current and left accounts</option>
                <option value="current">Current members</option>
                <option value="left">Left clan</option>
              </select>
            </label>
            <fieldset>
              <legend>Town halls</legend>
              {halls.map((value) => (
                <label key={value}>
                  <input
                    type="checkbox"
                    checked={filters.townHalls.includes(value)}
                    onChange={() =>
                      change({ townHalls: toggle(filters.townHalls, value) })
                    }
                  />
                  TH{value}
                </label>
              ))}
            </fieldset>
          </div>
        </details>
      </div>
      <p className="strike-activity-summary" role="status">
        {counts.risk} at risk · {counts.watch} watch · {counts.active} active
        {loadedAt ? ` · Updated ${loadedAt}` : ""}
      </p>
      {error && (
        <p className="notice error" role="alert">
          {error}
          {data.accounts.length ? " Showing the last loaded activity." : ""}
        </p>
      )}
      {data.activity_warning && (
        <p className="notice error">{data.activity_warning}</p>
      )}
      {data.weight_warning && (
        <p className="notice error">{data.weight_warning}</p>
      )}
      {data.identity_warning && (
        <p className="notice error">{data.identity_warning}</p>
      )}
      <h2 ref={headingRef} tabIndex={-1}>
        Family accounts <small>({visible.length})</small>
      </h2>
      {loading && !data.accounts.length ? (
        <p role="status">Loading family activity…</p>
      ) : !error && !rows.length ? (
        <div className="card empty">
          <p>
            {data.accounts.length
              ? "No accounts match these filters."
              : "No family accounts have been observed yet."}
          </p>
          <button onClick={() => change(parseActivityFilters())}>
            Clear filters
          </button>
        </div>
      ) : null}
      <div className="strike-activity-list">
        {rows.map((row) => (
          <button
            key={row.player_tag}
            data-strike-player={row.player_tag}
            className="strike-activity-row"
            onClick={() => choose(row)}
          >
            <span className="strike-activity-main">
              <span className={`strike-activity-badge ${row.status}`}>
                {activityStatusLabels[row.status]}
              </span>
              <span className="strike-activity-identity">
                <strong>{row.player_name}</strong>
                <span>
                  TH{row.town_hall || "—"} ·{" "}
                  {row.current_clan_name || row.last_clan_name || "No clan"} ·{" "}
                  {row.weight
                    ? compactWeight(row.weight)
                    : "Weight unavailable"}
                </span>
              </span>
              <span className="strike-activity-count">
                {row.active_strikes > 0 ? "⚠ " : ""}
                {row.active_strikes}{" "}
                {row.active_strikes === 1 ? "strike" : "strikes"}
              </span>
            </span>
            {row.replacement_note && (
              <span
                className="strike-activity-note"
                title={row.replacement_note}
              >
                {row.replacement_note}
              </span>
            )}
            <span className="strike-activity-chips">
              {activityChips(row).map((chip) => (
                <span
                  className={`strike-activity-chip ${chip.tone}`}
                  key={chip.label}
                >
                  {chip.label}
                </span>
              ))}
            </span>
          </button>
        ))}
      </div>
      {visible.length > 25 && (
        <nav
          className="strike-activity-pages"
          aria-label="Family account pages"
        >
          <button disabled={!page} onClick={() => change({ page: page - 1 })}>
            Previous accounts
          </button>
          <span>
            {page * 25 + 1}–{Math.min((page + 1) * 25, visible.length)} of{" "}
            {visible.length}
          </span>
          <button
            disabled={page >= lastPage}
            onClick={() => change({ page: page + 1 })}
          >
            Next accounts
          </button>
        </nav>
      )}
      <details onToggle={(event) => setTools(event.currentTarget.open)}>
        <summary>Match a recruit’s weight</summary>
        {tools && <RecruitWeightTool rows={data.accounts} onChoose={choose} />}
      </details>
    </section>
  );
}
function RecruitWeightTool({
  rows,
  onChoose,
}: {
  rows: ActivityAccount[];
  onChoose: (row: ActivityAccount) => void;
}) {
  const [weight, setWeight] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [matches, setMatches] = useState<
      {
        player_tag: string;
        player_name: string;
        weight: number;
        clan_name: string;
      }[]
    >([]);
  const current = useRef(0);
  useEffect(
    () => () => {
      current.current++;
    },
    [],
  );
  async function find() {
    const value = Number(weight);
    if (!Number.isFinite(value) || value <= 0) {
      setError("Enter a positive recruit weight.");
      return;
    }
    const amount = enteredWeight(weight);
    const id = ++current.current;
    setBusy(true);
    setError("");
    try {
      const data = await api<{ candidates: typeof matches }>(
        `/strikes/replacements?weight=${Math.round(amount)}&limit=3`,
      );
      if (!Array.isArray(data.candidates))
        throw new Error("Weight matches are incomplete. Try again.");
      if (id === current.current) setMatches(data.candidates);
    } catch (cause) {
      if (id === current.current) {
        setMatches([]);
        setError(
          cause instanceof Error ? cause.message : "Weights are unavailable.",
        );
      }
    } finally {
      if (id === current.current) setBusy(false);
    }
  }
  return (
    <section className="strike-activity-recruit">
      <p>Find the three closest eligible replacement weights.</p>
      <label>
        Recruit weight
        <input
          inputMode="decimal"
          value={weight}
          onChange={(event) => {
            current.current++;
            setBusy(false);
            setMatches([]);
            setError("");
            setWeight(event.target.value);
          }}
          placeholder="149 or 149000"
        />
      </label>
      <button disabled={busy} onClick={() => void find()}>
        {busy ? "Finding…" : "Find closest weights"}
      </button>
      {error && <p role="alert">{error}</p>}
      <ul>
        {matches.map((item) => (
          <li key={item.player_tag}>
            <button
              disabled={!rows.some((row) => row.player_tag === item.player_tag)}
              onClick={() => {
                const row = rows.find(
                  (row) => row.player_tag === item.player_tag,
                );
                if (row) onChoose(row);
              }}
            >
              {item.player_name} · {item.clan_name} ·{" "}
              {compactWeight(item.weight)}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
