import { formatDateTime, formatTime } from "./format";
import FilterChips from "./FilterChips";
import SelectionActionBar from "./SelectionActionBar";
import ActionMenu, { type ActionMenuItem } from "./rosterUi/ActionMenu";
import ActionPanel from "./ActionPanel";
import "./members/Members.css";
import ReturnBatch from "./returns/ReturnBatch";
import {
  actionLabels,
  captureMonth,
  returnFrequency,
  canApply,
  clanSection,
  displayDate,
  type ReturnAction,
  type ReturnClan,
} from "./returns/model";
import "./returns/returns.css";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type {
  ManagementDocument,
  ManagementSection,
  ReturnStatus,
} from "./serverManagement";
import type { AnnouncementChannel } from "./announcements";
import "./ReturnReminderOverview.css";

export function ReturnStatusSummary({ status }: { status: ReturnStatus }) {
  return (
    <div className="return-status-grid">
      <article>
        <strong>{status.label}</strong>
        <span>{status.players} saved players</span>
        {status.every_minutes && (
          <span>{returnFrequency(status.every_minutes)}</span>
        )}
        <small>
          Last recorded send:{" "}
          {status.last_sent_at
            ? formatDateTime(new Date(status.last_sent_at))
            : "None recorded"}
        </small>
        {status.expires_at && (
          <small>
            Window ends: {formatDateTime(new Date(status.expires_at))}
          </small>
        )}
      </article>
    </div>
  );
}

export default function ReturnReminderOverview({
  onOpen,
  onDirty,
  active = true,
}: {
  active?: boolean;
  onOpen: (section: ManagementSection) => void;
  onDirty?: (dirty: boolean) => void;
}) {
  const [aboutTrigger, setAboutTrigger] = useState<HTMLElement | null>(null);
  const [records, setRecords] = useState<ReturnClan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [section, setSection] = useState<"FWA" | "MAIN">("FWA");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [batch, setBatch] = useState<{
    action: ReturnAction;
    clans: ReturnClan[];
    hiddenIds: string[];
  } | null>(null);
  const [loadedAt, setLoadedAt] = useState("");
  const [destinationIds, setDestinationIds] = useState<
    Record<"MAIN" | "FWA", string | null>
  >({ MAIN: null, FWA: null });
  const [channelNames, setChannelNames] = useState<Record<string, string>>({});
  const [destinationError, setDestinationError] = useState("");
  const [destinationLoading, setDestinationLoading] = useState(true);
  const destinationRequest = useRef(0);
  const focusTarget = useRef<HTMLElement | null>(null);
  const request = useRef(0);
  const loadDestinations = useCallback(async () => {
    const id = ++destinationRequest.current;
    setDestinationLoading(true);
    setDestinationError("");
    try {
      const config = await api<ManagementDocument>("/manage/return-channels");
      if (id !== destinationRequest.current) return;
      const values = Object.fromEntries(
        config.fields.map((field) => [field.key, String(field.value || "")]),
      );
      setDestinationIds({
        MAIN: values.main_channel_id || null,
        FWA: values.fwa_channel_id || null,
      });
      try {
        const result = await api<{ channels: AnnouncementChannel[] }>(
          "/announcement-channels",
        );
        if (id === destinationRequest.current)
          setChannelNames(
            Object.fromEntries(
              result.channels.map((channel) => [channel.id, channel.name]),
            ),
          );
      } catch (cause) {
        if (id === destinationRequest.current) {
          setChannelNames({});
          setDestinationError(
            "Channel names could not be loaded; destination IDs remain visible.",
          );
          if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
            setRecords([]);
            setSelected([]);
            setError(cause.message);
          }
        }
      }
    } catch (cause) {
      if (id !== destinationRequest.current) return;
      setDestinationIds({ MAIN: null, FWA: null });
      setChannelNames({});
      setDestinationError("Destination settings could not be loaded.");
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
        setRecords([]);
        setSelected([]);
        setError(cause.message);
      }
    } finally {
      if (id === destinationRequest.current) setDestinationLoading(false);
    }
  }, []);
  useEffect(() => {
    if (active) focusTarget.current?.focus();
  }, [active]);
  const load = useCallback(async () => {
    const id = ++request.current;
    setLoading(true);
    setError("");
    try {
      const result = await api<ManagementDocument>("/manage/return-reminders");
      if (id !== request.current) return;
      setRecords(result.documents || []);
      setLoadedAt(formatTime(new Date()));
      setSelected((current) =>
        current.filter((id) => result.documents?.some((row) => row.id === id)),
      );
    } catch (cause) {
      if (id !== request.current) return;
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
        setRecords([]);
        setSelected([]);
        setLoadedAt("");
      }
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not load return reminders.",
      );
    } finally {
      if (id === request.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    if (active) {
      void load();
      void loadDestinations();
    }
    return () => {
      request.current++;
      destinationRequest.current++;
    };
  }, [load, loadDestinations, active]);
  useEffect(() => {
    onDirty?.(!!batch);
    return () => onDirty?.(false);
  }, [!!batch, onDirty]);
  const clans = records.filter((row) => row.return_status);
  const group = clans.filter((row) => clanSection(row) === section);
  const visible = group.filter(
    (row) =>
      (filter === "all" || row.return_status?.state === filter) &&
      `${row.label} ${row.id}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
  );
  const chosen = group.filter((row) => selected.includes(row.id));
  const hidden = chosen.filter(
    (row) => !visible.some((value) => value.id === row.id),
  );
  const openBatch = (action: ReturnAction) =>
    setBatch({ action, clans: chosen, hiddenIds: hidden.map((row) => row.id) });
  const destinationId = destinationIds[section];
  const destinationName = destinationLoading
    ? "Checking destination…"
    : destinationId
      ? channelNames[destinationId]
        ? `#${channelNames[destinationId]}`
        : `Channel ${destinationId}`
      : destinationError
        ? "Destination unavailable"
        : "No channel configured";
  const utility = (id: string) => {
    const row = records.find((row) => row.id === id);
    if (row) onOpen(row);
  };
  const pauseAction: ReturnAction =
    chosen.length > 0 &&
    chosen.every((row) => row.return_status?.state === "paused")
      ? "resume"
      : "pause";
  const actions: ReturnAction[] =
    section === "FWA"
      ? [
          "frequency",
          pauseAction,
          "send",
          "away",
          "start",
          ...(pauseAction === "pause" &&
          chosen.some((row) => row.return_status?.state === "paused")
            ? ["resume" as const]
            : []),
          "save",
          "replace",
          "clear",
        ]
      : ["save", "send", "away", "replace", "clear"];
  const applicable = (action: ReturnAction) =>
    visible.some((row) => selected.includes(row.id) && canApply(row, action));
  const menuAction = (action: ReturnAction): ActionMenuItem => ({
    id: action,
    label: actionLabels[action],
    disabled: chosen.length > 50 || !applicable(action),
    onAction: () => openBatch(action),
    danger: action === "replace" || action === "clear",
  });
  const primaryIds: ReturnAction[] =
    section === "FWA" ? ["frequency", pauseAction] : [];
  const overflow = actions
    .filter((action) => !primaryIds.includes(action) && applicable(action))
    .map(menuAction);
  const firstDanger = overflow.findIndex((action) => action.danger);
  if (firstDanger >= 0)
    overflow[firstDanger] = { ...overflow[firstDanger], separatorBefore: true };
  return (
    <section
      className="return-overview"
      aria-label="Return reminder overview"
      onClickCapture={(event) => {
        const target = (event.target as HTMLElement).closest("button");
        if (target && !batch) focusTarget.current = target;
      }}
    >
      <p className="return-cycle">{captureMonth()}</p>
      <div className="return-toolbar">
        <FilterChips
          className="return-clan-type filter-chips--flow"
          label="Home clan type"
          options={(["FWA", "MAIN"] as const).map((value) => {
            return {
              value: value,
              label: <>{value === "MAIN" ? "Main" : value}</>,
              count: clans.filter((row) => clanSection(row) === value).length,
            };
          })}
          value={section}
          onChange={(value) => {
            setSection(value);
            setFilter("all");
            setSelected([]);
          }}
          disabled={!!batch}
          variant="pill"
          role="group"
          revealSelection
        />
      </div>
      {aboutTrigger && (
        <ActionPanel
          className="return-about-panel"
          title="About this page"
          trigger={aboutTrigger}
          onClose={() => setAboutTrigger(null)}
        >
          <div className="return-context">
            <span>
              <strong>Purpose</strong>Bring saved members back to their home
              clans after CWL.
            </span>
            <span>
              <strong>Destination</strong>
              {destinationName}
            </span>
            <span>
              <strong>Timing</strong>
              {section === "FWA"
                ? "Automatic after start; stops at cutoff"
                : "Manual send only"}
            </span>
          </div>
        </ActionPanel>
      )}
      {destinationError && (
        <p className="return-destination-warning" role="status">
          {destinationError}{" "}
          <button type="button" onClick={() => void loadDestinations()}>
            Retry destination
          </button>
        </p>
      )}
      {error && (
        <div className="notice error" role="alert">
          {error}
          {loadedAt && " Showing the last loaded overview."}
          <button
            disabled={loading}
            onClick={() => {
              void load();
              void loadDestinations();
            }}
          >
            Retry
          </button>
        </div>
      )}
      {loading && <p role="status">Loading return lists…</p>}
      {batch && (
        <ReturnBatch
          key={batch.action + batch.clans.map((row) => row.id).join(",")}
          {...batch}
          onClose={() => {
            setBatch(null);
            requestAnimationFrame(() => focusTarget.current?.focus());
          }}
          onDone={() => {
            void load();
            void loadDestinations();
          }}
        />
      )}
      <fieldset disabled={!!batch || loading || (!!error && !records.length)}>
        <div className="members-search-line return-search-line">
          <label>
            <span className="members-search-label">Find a clan</span>
            <input
              type="search"
              value={query}
              placeholder="Find a clan"
              onChange={(event) => {
                setQuery(event.target.value);
              }}
            />
          </label>
          <div className="members-filter-tools">
            <details
              className="members-more-filters"
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  event.currentTarget.open = false;
                  event.currentTarget
                    .querySelector<HTMLElement>("summary")
                    ?.focus();
                }
              }}
            >
              <summary>
                Filters
                {filter !== "all" && (
                  <span aria-label="1 active filter"> · 1</span>
                )}
              </summary>
              <div className="members-filter-panel">
                <label>
                  Status
                  <select
                    value={filter}
                    onChange={(event) => {
                      setFilter(event.target.value);
                    }}
                  >
                    <option value="all">All statuses</option>
                    {(section === "FWA"
                      ? [
                          ["scheduled", "Running / scheduled"],
                          ["paused", "Paused"],
                          ["idle", "Not started"],
                          ["not_saved", "No saved list"],
                          ["expired", "Window ended"],
                        ]
                      : [
                          ["manual", "Ready for manual sends"],
                          ["not_saved", "No saved list"],
                          ["expired", "Window ended"],
                        ]
                    ).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </details>
          </div>
          <ActionMenu
            name="Return reminders"
            disabled={!!batch}
            items={[
              {
                id: "refresh",
                label: "Refresh",
                disabled: loading,
                onAction: () => {
                  void load();
                  void loadDestinations();
                },
              },
              {
                id: "channels",
                label: "Return channels",
                disabled: loading,
                onAction: () => utility("return-channels"),
              },
              {
                id: "about",
                label: "About this page",
                onAction: setAboutTrigger,
              },
            ]}
          />
        </div>
        {chosen.length > 0 && (
          <SelectionActionBar
            className="return-selection-bar"
            name="Clan selection"
            busy={!!batch || loading}
            label={`${chosen.length} selected${hidden.length ? ` (${hidden.length} hidden)` : ""}`}
            shortLabel={`${chosen.length} selected${hidden.length ? ` · ${hidden.length} hidden` : ""}`}
            onShow={() => {
              setQuery("");
              setFilter("all");
            }}
            actions={primaryIds.map(menuAction)}
            overflowActions={overflow}
            selectionActions={[
              {
                id: "all",
                label: "Select all",
                onAction: () =>
                  setSelected((current) => [
                    ...new Set([...current, ...visible.map((row) => row.id)]),
                  ]),
              },
              {
                id: "none",
                label: "Select none",
                onAction: () => setSelected([]),
              },
            ]}
            desktopSelection={
              <>
                <button
                  onClick={() =>
                    setSelected((current) => [
                      ...new Set([...current, ...visible.map((row) => row.id)]),
                    ])
                  }
                >
                  Select all
                </button>
                <button onClick={() => setSelected([])}>Select none</button>
              </>
            }
          />
        )}
        {chosen.length > 50 && (
          <p role="alert">Select up to 50 clans per action.</p>
        )}
        {section === "FWA" && chosen.length > 0 && (
          <details className="return-maintenance">
            <summary>Optional scheduling settings</summary>
            <p>
              Need a different window? Select one or more clans, then set their
              start and stop dates.
            </p>
            <button
              disabled={
                chosen.length > 50 ||
                chosen.some((row) => !canApply(row, "schedule"))
              }
              onClick={() => openBatch("schedule")}
            >
              Schedule for later ({chosen.length})
            </button>
          </details>
        )}
        <div className="return-clan-list">
          {visible.map((row) => (
            <article key={row.id} className="return-clan-row">
              <label className="return-clan-name">
                <input
                  type="checkbox"
                  checked={selected.includes(row.id)}
                  aria-label={`Select ${row.clan_name || row.label}`}
                  onChange={(event) =>
                    setSelected((current) =>
                      event.target.checked
                        ? [...current, row.id]
                        : current.filter((id) => id !== row.id),
                    )
                  }
                />
                <span>
                  <strong>{row.clan_name || row.label}</strong>
                  <small>
                    {row.clan_tag || row.id.replace(/^(MAIN|FWA)/, "")} ·{" "}
                    {row.return_status!.players} saved players
                  </small>
                </span>
              </label>
              <div>
                <strong>{row.return_status!.label}</strong>
                <small>
                  {section === "FWA"
                    ? row.return_status!.every_minutes
                      ? returnFrequency(row.return_status!.every_minutes)
                      : "No schedule"
                    : "Manual sends only"}
                </small>
              </div>
              <div className="return-window">
                {section === "FWA" && row.return_status!.starts_at && (
                  <small>
                    Started / scheduled:{" "}
                    {displayDate(row.return_status!.starts_at)}
                  </small>
                )}
                {row.return_status!.expires_at && (
                  <small>
                    {section === "FWA" ? "Automatically stops" : "List expires"}
                    : {displayDate(row.return_status!.expires_at)}
                  </small>
                )}
                <small>
                  Last sent:{" "}
                  {row.return_status!.last_sent_at
                    ? displayDate(row.return_status!.last_sent_at)
                    : "None recorded"}
                </small>
              </div>
              <div className="return-row-actions">
                <button onClick={() => onOpen(row)}>
                  Members &amp; details
                </button>
              </div>
            </article>
          ))}
        </div>
      </fieldset>
      {!loading && !error && !visible.length && (
        <p>
          {group.length
            ? "No clans match these filters."
            : "No home clans are available yet."}
        </p>
      )}
      <p className="return-health-note">
        {loadedAt && `Updated ${loadedAt}. `}Times are in your time zone.
      </p>
      <details className="return-maintenance">
        <summary>Recent actions &amp; list maintenance</summary>
        <div>
          <button disabled={!!batch} onClick={() => utility("return-history")}>
            Recent actions and results
          </button>
          {["replace", "clear"].map((operation) => (
            <button
              key={operation}
              disabled={!!batch}
              onClick={() => utility("return-bulk-" + operation)}
            >
              {operation === "replace"
                ? "Replace saved member lists"
                : "Clear member list"}
            </button>
          ))}
        </div>
      </details>
    </section>
  );
}
