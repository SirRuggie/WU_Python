import ClanCategories, { clanCategory } from "./ClanCategories";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { timeLabel } from "../warReminders/types";
import type { AnnouncementChannel } from "../announcements";
import type { Clan } from "./types";
import {
  rowHealth,
  destinationIssue,
  deliveryLabel,
  visibleRows,
  type OverviewData,
  type OverviewFilter,
} from "./reminderOverview";
import "./ReminderOverview.css";

type Props = {
  active: boolean;
  channels: AnnouncementChannel[];
  channelsReady: boolean;
  choicesError: string;
  onRetryChoices: () => void;
  onOpen: (clan: Clan) => void;
  returnTag: string | null;
  onAdd: () => void;
};
export default function ReminderOverview({
  active,
  channels,
  channelsReady,
  choicesError,
  onRetryChoices,
  onOpen,
  returnTag,
  onAdd,
}: Props) {
  const [data, setData] = useState<OverviewData | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const [query, setQuery] = useState(""),
    [filter, setFilter] = useState<OverviewFilter>("all");
  const [category, setCategory] = useState("");
  const generation = useRef(0),
    pending = useRef(false),
    heading = useRef<HTMLHeadingElement>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const load = useCallback(async () => {
    if (pending.current) return;
    pending.current = true;
    const turn = ++generation.current;
    setLoading(true);
    try {
      const result = await api<OverviewData>("/manage/war-reminders/overview");
      if (turn === generation.current) {
        setData(result);
        setError("");
      }
    } catch (e) {
      if (turn === generation.current) {
        if (e instanceof ApiError && [401, 403].includes(e.status))
          setData(null);
        setError(
          e instanceof Error
            ? e.message
            : "Could not load the family overview.",
        );
      }
    } finally {
      if (turn === generation.current) {
        pending.current = false;
        setLoading(false);
      }
    }
  }, []);
  useEffect(() => {
    if (!active) return;
    void load();
    if (returnTag)
      requestAnimationFrame(() => {
        (buttons.current.get(returnTag) || heading.current)?.focus();
      });
    const timer = setInterval(() => {
      if (!document.hidden) void load();
    }, 30000);
    return () => {
      clearInterval(timer);
      ++generation.current;
      pending.current = false;
    };
  }, [active, load, returnTag]);
  const names = new Map(
      channels
        .filter((c) => [0, 5].includes(c.type))
        .map((c) => [c.id, c.name]),
    ),
    ids = new Set(names.keys());
  const rows = data?.clans || [],
    visible = visibleRows(
      rows.filter(
        (row) => !category || clanCategory(row.clan.type) === category,
      ),
      query,
      filter,
      names,
      channelsReady,
    );
  const attention = rows.filter(
    (row) => rowHealth(row, ids, channelsReady).category === "attention",
  ).length;
  const enabled = rows.filter((row) => row.settings.enabled).length;
  const filters: [OverviewFilter, string, number][] = [
    ["all", "All statuses", rows.length],
    ["attention", "Needs attention", attention],
    ["enabled", "Enabled", enabled],
    ["off", "Off / not set up", rows.length - enabled],
  ];
  return (
    <section
      className="reminder-overview"
      aria-labelledby="reminder-overview-title"
    >
      <div className="overview-heading">
        <div>
          <p className="eyebrow">Family at a glance</p>
          <h2 id="reminder-overview-title" ref={heading} tabIndex={-1}>
            War reminders across your family
          </h2>
          <p>See what needs attention, then open a clan to make changes.</p>
        </div>
        <button
          disabled={loading}
          onClick={() => {
            void load();
            onRetryChoices();
          }}
        >
          {loading ? "Refreshing…" : "Refresh overview"}
        </button>
      </div>
      {error && (
        <p className="notice error" role="alert">
          {error} {data ? "Showing the last loaded overview." : ""}{" "}
          <button disabled={loading} onClick={() => void load()}>
            Retry overview
          </button>
        </p>
      )}
      {choicesError && (
        <p className="notice error" role="alert">
          Channel names could not be refreshed. Saved channel IDs are shown
          where needed.{" "}
          <button onClick={onRetryChoices}>Retry channel names</button>
        </p>
      )}
      {data && (
        <ClanCategories
          clans={rows.map((row) => row.clan)}
          value={category}
          onChange={setCategory}
        />
      )}
      {!data ? (
        <p role="status">
          {error
            ? "Overview unavailable. Retry to load your clans."
            : "Loading family reminders…"}
        </p>
      ) : (
        <>
          <div
            className="overview-filters"
            role="group"
            aria-label="Filter reminder overview"
          >
            {filters.map(([key, label, count]) => (
              <button
                key={key}
                aria-pressed={filter === key}
                onClick={() => setFilter(key)}
              >
                <span>{label}</span>
                <strong>{count}</strong>
              </button>
            ))}
          </div>
          <div className="overview-toolbar">
            <label>
              Find a clan or channel
              <input
                type="search"
                value={query}
                placeholder="Clan name, tag, type or channel"
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <div>
              <p role="status">
                {visible.length} of {rows.length} clans
              </p>
              <small>
                Updated{" "}
                {new Date(data.generated_at).toLocaleTimeString([], {
                  hour: "numeric",
                  minute: "2-digit",
                })}{" "}
                · refreshes every 30s
              </small>
            </div>
          </div>
          {!rows.length ? (
            <div className="overview-empty">
              <h3>Your family starts here</h3>
              <p>
                Add your first clan, then choose its reminder channel and times.
              </p>
              <button onClick={onAdd}>Add a clan</button>
            </div>
          ) : !visible.length ? (
            <div className="overview-empty">
              <h3>
                {filter === "attention" && !query
                  ? "No clans need attention"
                  : "No matching clans"}
              </h3>
              <p>
                {filter === "attention" && !query
                  ? "No issues are flagged in the latest stored checks."
                  : "Try another name or clear the filters."}
              </p>
              <button
                onClick={() => {
                  setQuery("");
                  setFilter("all");
                  setCategory("");
                }}
              >
                Show all clans
              </button>
            </div>
          ) : (
            <table className="overview-table">
              <caption className="overview-sr-only">
                Saved family war reminder settings and latest scheduled outcome.
                Test messages are excluded.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Clan</th>
                  <th scope="col">Reminders</th>
                  <th scope="col">Channel &amp; schedule</th>
                  <th scope="col">Last reminder</th>
                  <th scope="col">
                    <span className="overview-sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => {
                  const state = rowHealth(row, ids, channelsReady),
                    issue = destinationIssue(row, ids, channelsReady),
                    config = row.settings;
                  if (!config.enabled && state.category !== "attention") {
                    return (
                      <tr key={row.clan.tag} className="overview-off-row">
                        <td colSpan={5}>
                          <div className="overview-off-line">
                            <strong title={row.clan.name}>
                              {row.clan.name}
                            </strong>
                            <span>
                              {clanCategory(row.clan.type) || "Type not set"} ·
                              Off
                            </span>
                            <button
                              ref={(el) => {
                                if (el) buttons.current.set(row.clan.tag, el);
                                else buttons.current.delete(row.clan.tag);
                              }}
                              aria-label={`Set up reminders for ${row.clan.name}`}
                              onClick={() => onOpen(row.clan)}
                            >
                              Set up ›
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  }
                  return (
                    <tr key={row.clan.tag}>
                      <th scope="row">
                        <strong>{row.clan.name}</strong>
                        <small>
                          {row.clan.tag} ·{" "}
                          {clanCategory(row.clan.type) || "Type not set"}
                        </small>
                      </th>
                      <td>
                        <span
                          className={`overview-state overview-state-${state.category}`}
                        >
                          {state.label}
                        </span>
                        <small>{state.detail}</small>
                      </td>
                      <td>
                        <span
                          className="overview-mobile-label"
                          aria-hidden="true"
                        >
                          Channel &amp; schedule
                        </span>
                        <strong>
                          {config.channel_id
                            ? names.has(config.channel_id)
                              ? `#${names.get(config.channel_id)}`
                              : `Channel ${config.channel_id}`
                            : "No channel selected"}
                        </strong>
                        <small>
                          {state.category === "not_configured"
                            ? "Choose times during setup"
                            : config.war_started
                              ? "War start"
                              : ""}
                          {state.category !== "not_configured" &&
                          config.war_started &&
                          config.minutes.length
                            ? " · "
                            : ""}
                          {state.category !== "not_configured" &&
                            config.minutes
                              .slice(0, 3)
                              .map(timeLabel)
                              .join(", ")}
                          {!config.war_started && !config.minutes.length
                            ? "No times selected"
                            : ""}
                          {state.category !== "not_configured" &&
                          config.minutes.length
                            ? " before end"
                            : ""}
                          {state.category !== "not_configured" &&
                            config.minutes.length > 3 &&
                            ` · +${config.minutes.length - 3} more`}
                        </small>
                        {issue && <small role="status">{issue}</small>}
                      </td>
                      <td>
                        <span
                          className="overview-mobile-label"
                          aria-hidden="true"
                        >
                          Last reminder
                        </span>
                        <span>
                          {row.last_delivery
                            ? deliveryLabel(row.last_delivery.status)
                            : "No scheduled deliveries yet"}
                        </span>
                        {row.last_delivery && (
                          <small>
                            {new Date(row.last_delivery.at).toLocaleString()}
                          </small>
                        )}
                        <small>
                          {row.checked_at
                            ? `Last checked ${new Date(row.checked_at).toLocaleString()}`
                            : "Not checked yet"}
                        </small>
                      </td>
                      <td>
                        <button
                          ref={(el) => {
                            if (el) buttons.current.set(row.clan.tag, el);
                            else buttons.current.delete(row.clan.tag);
                          }}
                          aria-label={`${issue ? "Review destination" : "Manage reminders"} for ${row.clan.name} ${row.clan.tag}`}
                          onClick={() => onOpen(row.clan)}
                        >
                          {issue ? "Review destination" : "Manage reminders"}{" "}
                          <span aria-hidden="true">→</span>
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <p className="overview-note">
            Reminder times are relative to the active war. Monitoring is not
            proof of delivery.
          </p>
          <details className="overview-note">
            <summary>About reminder status</summary>
            <p>
              Exact upcoming timing depends on the active war’s end time, which
              is not available in this overview. A channel appearing in the
              server list does not confirm the bot can send there. Status uses
              saved settings and stored bot checks. Test messages appear only in
              each clan’s delivery history.
            </p>
          </details>
        </>
      )}
    </section>
  );
}
