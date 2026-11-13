import { Search, X } from "lucide-react";
import FilterChips from "./FilterChips";
import ActionMenu, { type ActionMenuItem } from "./rosterUi/ActionMenu";
import StrikeActivityRows from "./StrikeActivityRows";
import FindSlots from "./FindSlots";
import SortTrigger from "./rosterUi/SortTrigger";
import StrikeGroupHeading from "./StrikeGroupHeading";
import StrikeSortPanel from "./StrikeSortPanel";
import useCompactPreview from "./useCompactPreview";
import useDiscordIdentities from "./useDiscordIdentities";
import { activityPages } from "./strikeActivityGroups";
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
import { spendPanelEntry } from "./actionPanelHistory";
import StrikeBulkMark from "./StrikeBulkMark";
import type { ViewMemory } from "./strikeViewMemory";
import type { ActivityAccount } from "./strikeActivityView";
import StrikeActivityFiltersPanel from "./StrikeActivityFiltersPanel";
import {
  activityFilterQuery,
  activityFilterKeys,
  activityGroupLabels,
  activitySortLabels,
  activityRuleText,
  memberName,
  parseActivityFilters,
  clearActivityFilters,
  visibleActivityAccounts,
  activityViews,
  activityViewPreset,
  activityViewCounts,
  normalizeActivityView,
  appliedActivityFilters,
  copyActivityList,
  type ActivityFilters,
} from "./strikeActivityFilters";
import "./StrikeActivityRoster.css";
import { countLabel } from "./countLabel";

type Response = {
  accounts: ActivityAccount[];
  clans: { tag: string; name: string }[];
  weight_warning?: string;
  identity_warning?: string;
  activity_warning?: string;
  history_warning?: string;
  identity_updating?: boolean;
  activity_updating?: boolean;
  activity_checked_at?: string | null;
  activity_as_of?: string | null;
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
  overviewActions,
  trackingSlotRef,
}: {
  /** Account actions listed first in the toolbar ⋯ menu. */
  overviewActions?: ActionMenuItem[];
  trackingSlotRef?: (slot: HTMLDivElement | null) => void;
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
  const rosterRef = useRef<HTMLElement>(null);
  const chipsRef = useRef<HTMLDivElement>(null);
  const [moreChips, setMoreChips] = useState(false);
  const phone = useCompactPreview(760);
  const searchInput = useRef<HTMLInputElement>(null);
  const searchButton = useRef<HTMLButtonElement>(null);
  const searchFocus = useRef<"field" | "button" | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const scrolledView = useRef<string | null>(null);
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
  useEffect(() => {
    if (loading || scrolledView.current === filters.view) return;
    const row = rosterRef.current?.querySelector<HTMLElement>(
      ".strike-activity-tabs",
    );
    const selected = row?.querySelector<HTMLElement>('[aria-pressed="true"]');
    if (!row || !selected) return;
    scrolledView.current = filters.view;
    const rowBounds = row.getBoundingClientRect();
    const selectedBounds = selected.getBoundingClientRect();
    const left = rowBounds.left + row.clientLeft;
    const right = left + row.clientWidth;
    const delta =
      selectedBounds.left < left
        ? selectedBounds.left - left
        : selectedBounds.right > right
          ? selectedBounds.right - right
          : 0;
    if (!delta) {
      // Cancel an earlier smooth reveal before it moves this selection away.
      row.scrollTo({ left: row.scrollLeft, behavior: "instant" });
      return;
    }
    row.scrollTo({
      left: Math.max(
        0,
        Math.min(row.scrollWidth - row.clientWidth, row.scrollLeft + delta),
      ),
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }, [filters.view, loading]);
  const searching = searchOpen || filters.query !== "";
  useEffect(() => {
    const target =
      searchFocus.current === "field"
        ? searchInput.current
        : searchFocus.current === "button"
          ? searchButton.current
          : null;
    if (!target) return;
    searchFocus.current = null;
    target.focus();
  }, [searching]);
  const [filterTrigger, setFilterTrigger] = useState<HTMLElement | null>(null);
  const [sortTrigger, setSortTrigger] = useState<HTMLElement | null>(null);
  const copyIdentity = useRef(filterIdentity);
  copyIdentity.current = filterIdentity;
  async function copyList() {
    const current = filterIdentity;
    try {
      await navigator.clipboard.writeText(copyActivityList(visible));
      if (copyIdentity.current !== current) return;
      setCopied(`Copied ${countLabel(visible.length, "account")}`);
    } catch {
      if (copyIdentity.current !== current) return;
      setCopied("Copy failed. Your browser did not allow clipboard access.");
    }
  }
  const [copied, setCopied] = useState("");
  useEffect(() => {
    setCopied("");
  }, [filterIdentity]);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(""), 4000);
    return () => clearTimeout(timer);
  }, [copied]);
  const [selecting, setSelecting] = useState(false),
    [selected, setSelected] = useState<string[]>([]),
    [bulkBusy, setBulkBusy] = useState(false);
  const writeEpoch = useRef(0);
  const bulkWorking = useCallback(
    (value: boolean) => {
      if (value) writeEpoch.current++;
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
    enabled:
      !!data.identity_updating ||
      !!data.identity_warning ||
      !!data.activity_updating,
    generation: request.current,
    busy: () => pending.current || bulkBusy,
    readVersion: () =>
      `${request.current}:${writeEpoch.current}:${selectionReset}`,
    onResult: (result) =>
      setData((current) => ({
        ...current,
        identity_warning: result.identity_warning ?? undefined,
        identity_updating: result.identity_updating,
        ...(current.activity_updating
          ? {
              accounts: result.accounts,
              clans: result.clans ?? current.clans,
              activity_updating: result.activity_updating,
              activity_checked_at: result.activity_checked_at,
              activity_as_of: result.activity_as_of,
              activity_warning: result.activity_warning ?? undefined,
              history_warning: result.history_warning ?? undefined,
              weight_warning: result.weight_warning ?? undefined,
            }
          : {
              accounts: mergeIdentityAccounts(
                current.accounts,
                result.accounts,
              ),
            }),
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
  const counts = activityViewCounts(data.accounts, filters.includeLow, filters),
    pages = useMemo(
      () => activityPages(visible, filters.group),
      [visible, filters.group],
    ),
    lastPage = Math.max(0, pages.length - 1),
    page = Math.min(filters.page, lastPage);
  const rows = pages[page] ?? [];
  const pageStart = pages
    .slice(0, page)
    .reduce((total, items) => total + items.length, 0);
  const memberLabel = filters.member
    ? (data.accounts
        .filter((row) => row.discord_id === filters.member)
        .map(memberName)
        .find(Boolean) ?? null)
    : null;
  const profiles = useDiscordIdentities(
    rows.map((row) => row.discord_id),
    filters.group === "discord" && !!rows.length,
    "/strikes/members",
  );
  useEffect(() => {
    if (profiles.denied) callbacks.current.onDenied?.();
  }, [profiles.denied]);
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
    if (
      Object.keys(patch).some(
        (key) => key !== "page" && key !== "sort" && key !== "direction",
      )
    )
      setSelected([]);
    const next = normalizeActivityView({
      ...filters,
      ...patch,
      page: "page" in patch ? patch.page! : 0,
    });
    setLocal(next);
    // A route change under an open panel moves it to a new entry; keep the
    // marker there so a nested panel's Back still lands on this panel.
    const panel = history.state?.wuActionPanel;
    if (onState) {
      onState(activityFilterQuery(next), push);
      if (panel)
        history.replaceState(spendPanelEntry(history.state, panel), "");
    } else {
      const url = new URL(window.location.href);
      for (const key of activityFilterKeys) url.searchParams.delete(key);
      new URLSearchParams(activityFilterQuery(next)).forEach((value, key) =>
        url.searchParams.append(key, value),
      );
      const historyState = panel
        ? spendPanelEntry(history.state, panel)
        : { ...history.state };
      history.replaceState(historyState, "", url.pathname + url.search);
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
  const clearedFilters = clearActivityFilters(filters);
  const hasExtraFilters = appliedActivityFilters(
    filters,
    data.clans,
    memberLabel,
  ).some(
    (filter) =>
      JSON.stringify(normalizeActivityView({ ...filters, ...filter.clear })) !==
      JSON.stringify(filters),
  );
  useEffect(() => {
    const row = chipsRef.current?.querySelector<HTMLElement>(
      ".strike-activity-tabs",
    );
    if (!row) return;
    const measure = () =>
      setMoreChips(row.scrollWidth - row.clientWidth - row.scrollLeft > 1);
    measure();
    row.addEventListener("scroll", measure, { passive: true });
    window.addEventListener("resize", measure);
    const observer =
      typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    observer?.observe(row);
    return () => {
      row.removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
      observer?.disconnect();
    };
  }, [loading, data.accounts, filterIdentity, phone]);
  const countsPending = loading || !!data.activity_updating;
  const countText = (view: (typeof activityViews)[number]) =>
    countsPending ? "…" : error && !data.accounts.length ? "–" : counts[view];
  const viewLabels = {
    not_attacking: "Not attacking",
    inactive: "Inactive",
    replacements: "Replacements",
    all: "All",
  } as const;
  const clanOf = (row: ActivityAccount) =>
    (row.left_clan ? row.last_clan_tag : row.current_clan_tag) || "";
  const clanOptions = [
    ...data.clans,
    ...(filters.clans.length === 1 &&
    !data.clans.some((clan) => clan.tag === filters.clans[0])
      ? [{ tag: filters.clans[0], name: filters.clans[0] }]
      : []),
  ]
    .map((clan) => ({
      tag: clan.tag,
      name: clan.name,
      count: data.accounts.filter((row) => clanOf(row) === clan.tag).length,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
  const hallOptions = [
    ...new Set([
      ...data.accounts
        .map((row) => row.town_hall)
        .filter((hall): hall is number => !!hall),
      ...(filters.townHalls.length === 1 ? filters.townHalls : []),
    ]),
  ]
    .sort((a, b) => b - a)
    .map((hall) => ({
      hall,
      count: data.accounts.filter((row) => row.town_hall === hall).length,
    }));
  const findSlots = filters.view === "replacements" &&
    !(loading && !data.accounts.length) && (
      <FindSlots
        clans={data.clans}
        accounts={data.accounts}
        search={{
          slotWeights: filters.slotWeights,
          slotClans: filters.slotClans,
          slotMember: filters.slotMember,
        }}
        disabled={bulkBusy}
        onSearch={(next) => change(next, false)}
        onChoose={choose}
      />
    );
  return (
    <section
      ref={rosterRef}
      className={`strike-activity-roster${findSlots ? " has-find-slots" : ""}`}
      aria-label="Family activity overview"
    >
      <div
        ref={chipsRef}
        className={`strike-activity-chips${moreChips ? " has-more" : ""}`}
      >
        {phone ? (
          <select
            className="strike-activity-view-select"
            aria-label="View"
            value={filters.view}
            disabled={bulkBusy}
            onChange={(event) =>
              change(
                activityViewPreset(
                  filters,
                  event.target.value as (typeof activityViews)[number],
                ),
              )
            }
          >
            {activityViews.map((view) => (
              <option key={view} value={view}>
                {viewLabels[view]} ({countText(view)})
              </option>
            ))}
          </select>
        ) : (
          <FilterChips
            variant="pill"
            className="strike-activity-tabs"
            label="Account views"
            value={filters.view}
            disabled={bulkBusy}
            options={activityViews.map((view) => ({
              value: view,
              label: viewLabels[view],
              count: countText(view),
            }))}
            onChange={(view) => change(activityViewPreset(filters, view))}
          />
        )}
      </div>
      <div className="strike-activity-selectors">
        <select
          aria-label="Clan"
          value={filters.clans.length > 1 ? "many" : (filters.clans[0] ?? "")}
          disabled={bulkBusy}
          onChange={(event) =>
            change({ clans: event.target.value ? [event.target.value] : [] })
          }
        >
          <option value="">All clans</option>
          {filters.clans.length > 1 && (
            <option value="many" disabled>
              {filters.clans.length} clans
            </option>
          )}
          {clanOptions.map((clan) => (
            <option key={clan.tag} value={clan.tag}>
              {clan.name} · {clan.count}
            </option>
          ))}
        </select>
        <select
          aria-label="Town Hall"
          value={
            filters.townHalls.length > 1
              ? "many"
              : String(filters.townHalls[0] ?? "")
          }
          disabled={bulkBusy}
          onChange={(event) =>
            change({
              townHalls: event.target.value ? [Number(event.target.value)] : [],
            })
          }
        >
          <option value="">Any TH</option>
          {filters.townHalls.length > 1 && (
            <option value="many" disabled>
              {filters.townHalls.length} Town Halls
            </option>
          )}
          {hallOptions.map((option) => (
            <option key={option.hall} value={option.hall}>
              TH{option.hall} · {option.count}
            </option>
          ))}
        </select>
      </div>
      <div className="strike-activity-toolbar">
        <button
          ref={searchButton}
          type="button"
          className="strike-activity-search-button"
          aria-label="Find account or member"
          aria-expanded={searching}
          onClick={() => {
            searchFocus.current = "field";
            setSearchOpen(true);
            searchInput.current?.focus();
          }}
        >
          <Search size={18} aria-hidden="true" />
        </button>
        <div className="roster-ui strike-activity-sort">
          <SortTrigger
            disabled={bulkBusy}
            label={activitySortLabels[filters.sort]}
            grouped={
              filters.group === "none"
                ? false
                : activityGroupLabels[filters.group]
            }
            onClick={(event) => setSortTrigger(event.currentTarget)}
          />
        </div>
        <button
          className="strike-activity-filters-button"
          disabled={bulkBusy}
          onClick={(event) => setFilterTrigger(event.currentTarget)}
        >
          Filters
        </button>
        <ActionMenu
          name="Activity"
          items={[
            ...(overviewActions || []),
            {
              id: "copy-list",
              label: "Copy list",
              separatorBefore: !!overviewActions?.length,
              disabled: !visible.length,
              onAction: () => void copyList(),
            },
            ...(canManage && !selecting
              ? [
                  {
                    id: "select-accounts",
                    label: "Select accounts",
                    disabled: bulkBusy,
                    onAction: () => setSelecting(true),
                  },
                ]
              : []),
            {
              id: "refresh-activity",
              label: "Refresh activity",
              disabled: loading || bulkBusy,
              onAction: () => void read(),
            },
          ]}
        />
      </div>
      {searching && (
        <div className="strike-activity-search">
          <input
            ref={searchInput}
            aria-label="Find account or member"
            type="search"
            value={filters.query}
            maxLength={80}
            placeholder="Name, tag or member"
            onChange={(event) => change({ query: event.target.value }, false)}
          />
          <button
            type="button"
            className="strike-activity-search-close"
            aria-label="Clear search"
            onClick={() => {
              searchFocus.current = "button";
              setSearchOpen(false);
              change({ query: "" }, false);
            }}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
      )}
      {findSlots}
      {sortTrigger && (
        <StrikeSortPanel
          filters={filters}
          trigger={sortTrigger}
          onClose={() => setSortTrigger(null)}
          onChange={(patch) => change(patch)}
        />
      )}
      {filterTrigger && (
        <StrikeActivityFiltersPanel
          filters={filters}
          accounts={data.accounts}
          trigger={filterTrigger}
          onClose={() => setFilterTrigger(null)}
          onApply={(next) => {
            change(next);
            setFilterTrigger(null);
          }}
        />
      )}
      <div className="strike-activity-status">
        <div className="strike-activity-status-line">
          <div className="strike-activity-rule-line">
            <p className="strike-activity-rule">
              {activityRuleText(filters, memberLabel)}
            </p>
            <div className="strike-activity-applied">
              {appliedActivityFilters(filters, data.clans, memberLabel).map(
                (filter) => {
                  const next = normalizeActivityView({
                    ...filters,
                    ...filter.clear,
                  });
                  // A rule the tab always applies is the rule line above, not a chip.
                  if (
                    Object.keys(filter.clear).every(
                      (key) =>
                        next[key as keyof ActivityFilters] ===
                        filters[key as keyof ActivityFilters],
                    )
                  )
                    return null;
                  return (
                    <button
                      key={filter.key}
                      aria-label={`Remove ${filter.label}`}
                      onClick={() => change(filter.clear)}
                    >
                      {filter.label} ×
                    </button>
                  );
                },
              )}
            </div>
            <p
              className="strike-activity-summary"
              role="status"
              title={loadedAt ? `Updated ${loadedAt}` : undefined}
            >
              {(error
                ? "Activity unavailable"
                : loading && !data.accounts.length
                  ? "Loading accounts…"
                  : "") ||
                `Showing ${visible.length} of ${data.accounts.length}`}
            </p>
          </div>
          <div className="strike-activity-freshness">
            {data.activity_updating ? (
              <p className="strike-activity-as-of">Loading activity…</p>
            ) : data.activity_as_of ? (
              <p className="strike-activity-as-of">{data.activity_as_of}</p>
            ) : null}
            <div
              className="strike-activity-tracking-slot"
              ref={trackingSlotRef}
            />
          </div>
        </div>
      </div>
      {copied && (
        <div className="strike-copy-toast" role="status">
          {copied}
        </div>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
          {data.accounts.length ? " Showing the last loaded activity." : ""}
        </p>
      )}
      {data.history_warning && (
        <p className="notice error">{data.history_warning}</p>
      )}
      {data.activity_warning && !data.activity_updating && (
        <p className="notice error">{data.activity_warning}</p>
      )}
      {data.weight_warning && (
        <p className="notice error">{data.weight_warning}</p>
      )}
      {data.identity_warning && !data.identity_updating && (
        <p className="muted" role="status">
          {data.identity_warning}
        </p>
      )}
      <h2 className="sr-only" ref={headingRef} tabIndex={-1}>
        Family accounts <small>({visible.length})</small>
      </h2>
      {loading && !data.accounts.length ? (
        <p role="status">Loading family activity…</p>
      ) : !error && !rows.length ? (
        <div className="card empty">
          <p>
            {data.accounts.length
              ? hasExtraFilters
                ? `No accounts match these filters in the ${filters.view.replaceAll("_", " ")} tab.`
                : `No accounts in the ${filters.view.replaceAll("_", " ")} tab.`
              : "No family accounts have been observed yet."}
          </p>
          {hasExtraFilters && (
            <button onClick={() => change(clearedFilters)}>
              Clear filters
            </button>
          )}
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
        filters={filters}
        onSort={(sort) =>
          change({
            sort,
            direction:
              filters.sort === sort
                ? filters.direction === "asc"
                  ? "desc"
                  : "asc"
                : "desc",
          })
        }
        selecting={canManage && selecting}
        selected={selected}
        busy={bulkBusy}
        onSelected={setSelected}
        onChoose={choose}
        renderGroup={
          filters.group === "none"
            ? undefined
            : (head, members) => (
                <StrikeGroupHeading
                  head={head}
                  rows={members}
                  profiles={profiles.members}
                  resolving={profiles.loading}
                />
              )
        }
      />
      {pages.length > 1 && (
        <nav
          className="strike-activity-pages"
          aria-label="Family account pages"
        >
          <button disabled={!page} onClick={() => change({ page: page - 1 })}>
            Previous accounts
          </button>
          <span>
            {pageStart + 1}–{pageStart + rows.length} of {visible.length}
          </span>
          <button
            disabled={page >= lastPage}
            onClick={() => change({ page: page + 1 })}
          >
            Next accounts
          </button>
        </nav>
      )}
    </section>
  );
}
