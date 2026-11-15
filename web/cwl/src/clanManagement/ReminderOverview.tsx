import { formatDateTime } from "../format";
import LoadError from "../LoadError";
import { clanCategory } from "./ClanCategories";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import Switch from "../rosterUi/Switch";
import type { ReminderData } from "../warReminders/types";
import type { AnnouncementChannel } from "../announcements";
import type { Clan } from "./types";
import {
  rowHealth,
  destinationIssue,
  deliveryLabel,
  notSetUp,
  scheduleSummary,
  visibleRows,
  type OverviewData,
  type OverviewRow,
} from "./reminderOverview";
import ReminderOverviewFilters, {
  noOverviewFilters,
  statusLabels,
  type OverviewFilters,
} from "./ReminderOverviewFilters";
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
    [filters, setFilters] = useState<OverviewFilters>(noOverviewFilters),
    [panelTrigger, setPanelTrigger] = useState<HTMLElement | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({}),
    [busyTags, setBusyTags] = useState<string[]>([]);
  const generation = useRef(0),
    pending = useRef(false),
    inflight = useRef(new Set<string>()),
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
        // A row with a save in flight keeps its local state until that save ends.
        setData((old) => ({
          ...result,
          clans: result.clans.map(
            (row) =>
              (inflight.current.has(row.clan.tag) &&
                old?.clans.find((item) => item.clan.tag === row.clan.tag)) ||
              row,
          ),
        }));
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

  function patchRow(tag: string, patch: Partial<OverviewRow>) {
    setData((old) =>
      old
        ? {
            ...old,
            clans: old.clans.map((row) =>
              row.clan.tag === tag ? { ...row, ...patch } : row,
            ),
          }
        : old,
    );
  }
  async function toggle(row: OverviewRow, next: boolean) {
    const tag = row.clan.tag;
    if (inflight.current.has(tag)) return;
    inflight.current.add(tag);
    // A load that started before this toggle may finish after it; drop it.
    if (pending.current) {
      ++generation.current;
      pending.current = false;
      setLoading(false);
    }
    setBusyTags([...inflight.current]);
    setRowErrors((old) => ({ ...old, [tag]: "" }));
    const settings = { ...row.settings, enabled: next };
    patchRow(tag, { settings });
    let changedElsewhere = false;
    try {
      const result = await api<ReminderData>(
        `/manage/clans/${encodeURIComponent(tag)}/war-reminders`,
        "PUT",
        { settings, revision: row.revision },
      );
      patchRow(tag, { settings: result.settings, revision: result.revision });
    } catch (e) {
      patchRow(tag, { settings: row.settings });
      changedElsewhere = e instanceof ApiError && e.status === 409;
      setRowErrors((old) => ({
        ...old,
        [tag]: e instanceof Error ? e.message : "Could not save. Try again.",
      }));
    } finally {
      inflight.current.delete(tag);
      setBusyTags([...inflight.current]);
    }
    if (changedElsewhere) {
      pending.current = false;
      await load();
    }
  }

  const names = new Map(
      channels
        .filter((c) => [0, 5].includes(c.type))
        .map((c) => [c.id, c.name]),
    ),
    ids = new Set(names.keys());
  const rows = data?.clans || [],
    visible = visibleRows(
      rows,
      query,
      filters.filter,
      names,
      channelsReady,
      filters.category,
    );
  const activeChips: { label: string; clear: Partial<OverviewFilters> }[] = [
    ...(filters.category
      ? [{ label: filters.category, clear: { category: "" } }]
      : []),
    ...(filters.filter !== "all"
      ? [
          {
            label: statusLabels[filters.filter],
            clear: { filter: "all" as const },
          },
        ]
      : []),
  ];
  const remember = (tag: string) => (el: HTMLButtonElement | null) => {
    if (el) buttons.current.set(tag, el);
    else buttons.current.delete(tag);
  };
  return (
    <section
      className="reminder-overview"
      aria-labelledby="reminder-overview-title"
    >
      <h2 id="reminder-overview-title" ref={heading} tabIndex={-1}>
        War reminders across your family
      </h2>
      <LoadError
        message={[
          choicesError ? "Channel names could not be refreshed." : "",
          error,
        ]}
        note={data && error ? "Showing the last loaded overview." : undefined}
        disabled={loading}
        onRetry={() => {
          if (error) void load();
          if (choicesError) onRetryChoices();
        }}
      />
      {!data ? (
        <p role="status">
          {error
            ? "Overview unavailable. Select Try again to load your clans."
            : "Loading family reminders…"}
        </p>
      ) : (
        <>
          <div className="overview-tools">
            <label>
              Find a clan
              <input
                type="search"
                value={query}
                placeholder="Clan name, tag or channel…"
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <button
              aria-haspopup="dialog"
              onClick={(event) => setPanelTrigger(event.currentTarget)}
            >
              Filters{activeChips.length ? ` · ${activeChips.length}` : ""}
            </button>
          </div>
          {panelTrigger && (
            <ReminderOverviewFilters
              rows={rows}
              query={query}
              names={names}
              channelsReady={channelsReady}
              filters={filters}
              trigger={panelTrigger}
              onClose={() => setPanelTrigger(null)}
              onApply={(next) => {
                setFilters(next);
                setPanelTrigger(null);
              }}
            />
          )}
          {activeChips.length > 0 && (
            <div className="overview-applied">
              {activeChips.map((chip) => (
                <button
                  key={chip.label}
                  aria-label={`Remove filter ${chip.label}`}
                  onClick={() => setFilters({ ...filters, ...chip.clear })}
                >
                  {chip.label} <span aria-hidden="true">✕</span>
                </button>
              ))}
              <button onClick={() => setFilters(noOverviewFilters)}>
                Clear all
              </button>
            </div>
          )}
          <p className="overview-meta">
            <span role="status">
              {visible.length} of {rows.length} clans
            </span>{" "}
            · Updated{" "}
            {new Date(data.generated_at).toLocaleTimeString([], {
              hour: "numeric",
              minute: "2-digit",
            })}{" "}
            · refreshes every 30s
          </p>
          {!rows.length ? (
            <div className="overview-empty">
              <h3>Your family starts here</h3>
              <p>
                Add your first clan, then select its reminder channel and times.
              </p>
              <button onClick={onAdd}>Add a clan</button>
            </div>
          ) : !visible.length ? (
            <div className="overview-empty">
              <h3>
                {filters.filter === "attention" && !query && !filters.category
                  ? "No clans need attention"
                  : "No matching clans"}
              </h3>
              <p>
                {filters.filter === "attention" && !query && !filters.category
                  ? "No issues are flagged in the latest stored checks."
                  : "Try another name or clear the filters."}
              </p>
              <button
                onClick={() => {
                  setQuery("");
                  setFilters(noOverviewFilters);
                }}
              >
                Show all clans
              </button>
            </div>
          ) : (
            <ul className="overview-list" aria-label="War reminders by clan">
              {visible.map((row) => {
                const state = rowHealth(row, ids, channelsReady),
                  config = row.settings,
                  tag = row.clan.tag,
                  setUp = !notSetUp(row),
                  missing =
                    setUp && channelsReady && !names.has(config.channel_id),
                  issue = destinationIssue(row, ids, channelsReady) || missing,
                  type = clanCategory(row.clan.type) || "Type not set";
                const line = !setUp
                  ? "No channel selected"
                  : [
                      names.has(config.channel_id)
                        ? `#${names.get(config.channel_id)}`
                        : missing
                          ? "Channel missing · select a new one"
                          : "Channel name unavailable",
                      scheduleSummary(config) +
                        (config.enabled ? "" : " · saved"),
                      row.last_delivery
                        ? `${deliveryLabel(row.last_delivery.status)} ${formatDateTime(new Date(row.last_delivery.at))}`
                        : "No reminders sent yet",
                    ].join(" · ");
                return (
                  <li
                    key={tag}
                    className={`overview-row${setUp && !config.enabled ? " is-off" : ""}${state.category === "attention" ? " is-problem" : ""}`}
                  >
                    <div className="overview-row-text">
                      <p className="overview-row-name">
                        <strong title={row.clan.name}>{row.clan.name}</strong>
                        <span>{type}</span>
                      </p>
                      <p className="overview-row-line">{line}</p>
                      {state.category === "attention" && (
                        <p className="overview-row-issue" role="status">
                          {state.label} · {state.detail}
                        </p>
                      )}
                      {rowErrors[tag] && (
                        <p className="overview-row-error" role="alert">
                          {rowErrors[tag]}
                        </p>
                      )}
                    </div>
                    {setUp && (
                      <Switch
                        checked={config.enabled}
                        disabled={busyTags.includes(tag)}
                        problem={state.category === "attention"}
                        aria-label={`War reminders for ${row.clan.name}`}
                        onChange={(next) => void toggle(row, next)}
                      />
                    )}
                    <button
                      ref={remember(tag)}
                      aria-label={`${!setUp ? "Set up" : issue ? "Review" : "Edit"} reminders for ${row.clan.name}`}
                      onClick={() => onOpen(row.clan)}
                    >
                      {!setUp ? "Set up" : issue ? "Review" : "Edit"}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="overview-note">
            Times count back from the end of the active war. A status check does
            not prove a delivery.
          </p>
        </>
      )}
    </section>
  );
}
