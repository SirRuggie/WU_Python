import StrikeActivityRows from "./StrikeActivityRows";
import RecruitWeightTool from "./RecruitWeightTool";
import useActivityIdentityRefresh, {
  mergeIdentityAccounts,
} from "./useActivityIdentityRefresh";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import { api, ApiError } from "./api";
import StrikeBulkMark from "./StrikeBulkMark";
import type { ViewMemory } from "./strikeViewMemory";
import type { ActivityAccount } from "./strikeActivityView";
import StrikeActivityFiltersPanel from "./StrikeActivityFiltersPanel";
import {
  activityFilterQuery,
  activityFilterKeys,
  activitySorts,
  activitySortLabels,
  parseActivityFilters,
  visibleActivityAccounts,
  activityViews,
  activityViewPreset,
  activityViewCounts,
  normalizeActivityView,
  appliedActivityFilters,
  copyActivityList,
  type ActivityFilters,
  type ActivitySort,
} from "./strikeActivityFilters";
import "./StrikeActivityRoster.css";

type Response = {
  accounts: ActivityAccount[];
  clans: { tag: string; name: string }[];
  weight_warning?: string;
  identity_warning?: string;
  activity_warning?: string;
  history_warning?: string;
  identity_updating?: boolean;
};
export default function StrikeActivityRoster({
  state,
  canManage = false,
  selectionReset = 0,
  onWorking,
  onDirty,
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
  canManage?: boolean;
  selectionReset?: number;
  onWorking?: (value: boolean) => void;
  onDirty?: (value: boolean) => void;
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
  const filterIdentity = JSON.stringify({
    ...filters,
    page: 0,
    sort: "wars",
    direction: "desc",
  });
  useEffect(() => {
    setSelected([]);
    setSelecting(false);
  }, [filterIdentity, selectionReset]);
  const [data, setData] = useState<Response>({ accounts: [], clans: [] });
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [loadedAt, setLoadedAt] = useState("");
  const [tools, setTools] = useState(false);
  const [filterTrigger, setFilterTrigger] = useState<HTMLElement | null>(null);
  const [copied, setCopied] = useState("");
  const [selecting, setSelecting] = useState(false),
    [selected, setSelected] = useState<string[]>([]),
    [bulkBusy, setBulkBusy] = useState(false);
  const bulkWorking = useCallback(
    (value: boolean) => {
      setBulkBusy(value);
      onWorking?.(value);
    },
    [onWorking],
  );
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
      return true;
    } catch (cause) {
      if (current !== request.current) return false;
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
        setData({ accounts: [], clans: [] });
        callbacks.current.onDenied?.();
      }
      setError(
        cause instanceof Error
          ? cause.message
          : "Activity could not be loaded. Try again.",
      );
      return false;
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
  useActivityIdentityRefresh({
    enabled: !!data.identity_updating,
    generation: request.current,
    busy: () => pending.current || bulkBusy,
    onResult: (result) =>
      setData((current) => ({
        ...current,
        identity_warning: result.identity_warning ?? undefined,
        identity_updating: result.identity_updating,
        accounts: mergeIdentityAccounts(current.accounts, result.accounts),
      })),
    onDenied: () => {
      setData({ accounts: [], clans: [] });
      setError("Your activity access changed. Sign in or refresh permissions.");
      callbacks.current.onDenied?.();
    },
  });
  const visible = useMemo(
    () => visibleActivityAccounts(data.accounts, filters),
    [data.accounts, filters],
  );
  const counts = activityViewCounts(data.accounts, filters.includeLow),
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
    if (bulkBusy) return;
    if (Object.keys(patch).some((key) => key !== "page" && key !== "sort"))
      setSelected([]);
    const next = normalizeActivityView({
      ...filters,
      ...patch,
      page: "page" in patch ? patch.page! : 0,
    });
    setLocal(next);
    if (onState) onState(activityFilterQuery(next), push);
    else {
      const url = new URL(window.location.href);
      for (const key of activityFilterKeys) url.searchParams.delete(key);
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
  const selectable = visible.filter(
    (row) => row.current_clan_tag && !row.left_clan,
  );
  const selectedRows = data.accounts.filter((row) =>
    selected.includes(row.player_tag),
  );
  return (
    <section
      className="strike-activity-roster"
      aria-label="Family activity overview"
    >
      <div className="strike-activity-tabs" aria-label="Account views">
        {activityViews.map((view) => (
          <button
            key={view}
            aria-pressed={filters.view === view}
            disabled={bulkBusy}
            onClick={() => change(activityViewPreset(filters, view))}
          >
            {
              {
                not_attacking: "Not attacking",
                inactive: "Inactive",
                replacements: "Replacements",
                all: "All",
              }[view]
            }{" "}
            <small>{counts[view]}</small>
          </button>
        ))}
      </div>
      <div className="strike-activity-toolbar">
        <input
          aria-label="Find account or member"
          type="search"
          value={filters.query}
          maxLength={80}
          placeholder="Name, tag or member"
          onChange={(event) => change({ query: event.target.value }, false)}
        />
        <select
          aria-label="Sort accounts"
          value={filters.sort}
          onChange={(event) =>
            change({ sort: event.target.value as ActivitySort })
          }
        >
          {activitySorts.map((value) => (
            <option key={value} value={value}>
              {activitySortLabels[value]}
            </option>
          ))}
        </select>
        <button
          aria-label={
            filters.direction === "asc"
              ? "Ascending order; switch to descending"
              : "Descending order; switch to ascending"
          }
          onClick={() =>
            change({ direction: filters.direction === "asc" ? "desc" : "asc" })
          }
        >
          {filters.direction === "asc" ? "↑" : "↓"}
        </button>
        <button
          disabled={bulkBusy}
          onClick={(event) => setFilterTrigger(event.currentTarget)}
        >
          Filters
        </button>
        <details className="strike-activity-actions">
          <summary aria-label="Activity actions">⋯</summary>
          <div className="strike-activity-action-menu">
            <button disabled={loading || bulkBusy} onClick={() => void read()}>
              Refresh activity
            </button>
            <button
              disabled={!visible.length}
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(
                    copyActivityList(visible),
                  );
                  setCopied(`Copied ${visible.length} accounts`);
                } catch {
                  setCopied(
                    "Copy failed. Your browser did not allow clipboard access.",
                  );
                }
              }}
            >
              Copy list
            </button>
            {canManage && !selecting && (
              <button disabled={bulkBusy} onClick={() => setSelecting(true)}>
                Select accounts
              </button>
            )}
          </div>
        </details>
      </div>
      {filterTrigger && (
        <StrikeActivityFiltersPanel
          filters={filters}
          accounts={data.accounts}
          clans={data.clans}
          trigger={filterTrigger}
          onClose={() => setFilterTrigger(null)}
          onApply={(next) => {
            change(next);
            setFilterTrigger(null);
          }}
        />
      )}
      <div className="strike-activity-applied">
        {appliedActivityFilters(filters, data.clans).map((filter) => (
          <button
            key={filter.key}
            aria-label={`Remove ${filter.label}`}
            onClick={() => change(filter.clear)}
          >
            {filter.label} ×
          </button>
        ))}
      </div>
      <p className="strike-activity-summary" role="status">
        {(error
          ? "Activity unavailable"
          : loading && !data.accounts.length
            ? "Loading accounts…"
            : copied) ||
          `${visible.length} matching accounts${loadedAt ? ` · Updated ${loadedAt}` : ""}`}
      </p>
      {error && (
        <p className="notice error" role="alert">
          {error}
          {data.accounts.length ? " Showing the last loaded activity." : ""}
        </p>
      )}
      {data.history_warning && (
        <p className="notice error">{data.history_warning}</p>
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
      {canManage && selecting && (
        <div className="strike-activity-select">
          <button
            disabled={bulkBusy}
            aria-pressed={selecting}
            onClick={() => {
              setSelecting(!selecting);
              setSelected([]);
            }}
          >
            {selecting ? "Cancel selection" : "Select"}
          </button>
          {selecting && (
            <>
              <button
                disabled={
                  bulkBusy || selectable.length > 50 || !selectable.length
                }
                onClick={() =>
                  setSelected(selectable.map((row) => row.player_tag))
                }
              >
                Select all ({selectable.length})
              </button>
              <button
                disabled={bulkBusy || !selected.length}
                onClick={() => setSelected([])}
              >
                Clear selection
              </button>
              {selectable.length > 50 && (
                <small>Filter to 50 or fewer to select all.</small>
              )}
            </>
          )}
        </div>
      )}
      {canManage && selecting && (
        <StrikeBulkMark
          rows={selectedRows}
          onRemaining={setSelected}
          onRefresh={read}
          onBusy={bulkWorking}
          onDirty={onDirty}
          onSaved={() => {
            setSelected([]);
            setSelecting(false);
            void read();
          }}
        />
      )}
      <StrikeActivityRows
        rows={rows}
        selecting={canManage && selecting}
        selected={selected}
        busy={bulkBusy}
        onSelected={setSelected}
        onChoose={choose}
      />
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
