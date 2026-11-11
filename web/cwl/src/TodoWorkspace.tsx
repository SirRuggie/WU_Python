import SectionTabs from "./SectionTabs";
import "./rosterUi/tokens.css";
import { useJourneyState, useJourneyPosition } from "./journeyState";
import TodoActivityStatus, { TodoPrivateNote } from "./TodoActivityStatus";
import { loadTasks } from "./todoLoading";
import TodoTaskCard from "./TodoTaskCard";
import ClanGamesSummary from "./ClanGamesSummary";
import { withoutGamesScores } from "./todoSnapshot";
import DashboardIcon from "./DashboardIcon";
import TaskEventTimer from "./activity/TaskEventTimer";
import { useClock } from "./activity/useClock";
import PushReminders from "./PushReminders";
import { readSnapshot, writeSnapshot } from "./snapshotCache";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Pause, Play, RefreshCw, Search, X } from "lucide-react";
import { ApiError } from "./api";
import { clanDeepLink } from "./publication";
import TownHallIcon from "./TownHallIcon";
import {
  todoHasGaps,
  todoEmptyText,
  todoTabs,
  visibleTodoRows,
  type TodoKind,
  type TodoSnapshot,
  type TodoRow,
} from "./todo";
import "./TodoWorkspace.css";
import { readTodoPreferences, saveTodoPreferences } from "./todoPreferences";
function Badge({ url }: { url?: string | null }) {
  const [failed, setFailed] = useState("");
  return url && failed !== url ? (
    <img
      src={url}
      alt=""
      width={40}
      height={40}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(url)}
    />
  ) : (
    <DashboardIcon name="shield" />
  );
}
function clanLabel(row: TodoRow) {
  return row.clan_name || row.clan_tag || "Clan unknown";
}
export default function TodoWorkspace({
  userId,
  initialSearch = "",
  initialTab,
  onWars,
}: {
  userId: string;
  initialSearch?: string;
  initialTab?: TodoKind;
  onWars?: (kind: "war" | "cwl") => void;
}) {
  const journeyKey = `tasks:${userId}:${initialSearch}:${initialTab || "default"}`;
  const preferenceId = userId;
  const [preferences] = useState(() => {
    try {
      return readTodoPreferences(preferenceId, window.localStorage);
    } catch {
      return { tab: "war" as TodoKind, selected: null, sort: "deadline" };
    }
  });
  const cacheKey = `todo:${userId}`;
  const [data, setData] = useState<TodoSnapshot | null>(() => {
    const saved = readSnapshot<TodoSnapshot>(
      cacheKey,
      (value): value is TodoSnapshot => {
        const v = value as TodoSnapshot;
        return (
          !!v &&
          Array.isArray(v.accounts) &&
          typeof v.checked_at === "string" &&
          ["war", "cwl", "raid", "games", "private"].every((key) =>
            Array.isArray(v.views?.[key as TodoKind]?.rows),
          )
        );
      },
    );
    if (!saved) return null;
    const safe = withoutGamesScores(saved);
    writeSnapshot(cacheKey, safe);
    return safe;
  });
  const [cached, setCached] = useState(!!data);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [paused, setPaused] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [tab, setTab] = useJourneyState<TodoKind>(
    `${journeyKey}:tab`,
    initialTab || preferences.tab,
  );
  const [selected, setSelected] = useJourneyState<string[] | null>(
    `${journeyKey}:selected`,
    initialSearch ? null : preferences.selected,
  );
  const [accountSearch, setAccountSearch] = useState("");
  const [search, setSearch] = useJourneyState(
    `${journeyKey}:search`,
    initialSearch,
  );
  const [pickerOpen, setPickerOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const searchInput = useRef<HTMLInputElement>(null);
  const searchButton = useRef<HTMLButtonElement>(null);
  const accountsChip = useRef<HTMLButtonElement>(null);
  const focusAfterSearch = useRef<"input" | "button" | null>(null);
  // An active search always stays visible, so it never hides tasks unseen.
  // Once the field is used it stays open until the member closes it.
  const searchVisible = searchOpen || !!search;
  useEffect(() => {
    if (focusAfterSearch.current === "input") searchInput.current?.focus();
    if (focusAfterSearch.current === "button")
      (searchButton.current || accountsChip.current)?.focus();
    focusAfterSearch.current = null;
  }, [searchVisible]);
  const openSearch = () => {
    if (searchVisible) {
      searchInput.current?.focus();
      return;
    }
    focusAfterSearch.current = "input";
    setSearchOpen(true);
  };
  const closeSearch = () => {
    focusAfterSearch.current = "button";
    setSearch("");
    setSearchOpen(false);
  };
  const [sort, setSort] = useJourneyState(
    `${journeyKey}:sort`,
    preferences.sort,
  );
  useEffect(() => {
    try {
      if (!initialSearch)
        saveTodoPreferences(
          preferenceId,
          { tab, selected, sort },
          window.localStorage,
        );
    } catch {
      /* Storage can be blocked. */
    }
  }, [userId, tab, selected, sort]);
  const [page, setPage] = useJourneyState(`${journeyKey}:page`, 0);
  useJourneyPosition(journeyKey, !!data || !!error);
  const now = useClock();
  useEffect(() => {
    let cancelled = false,
      inFlight = false;
    const load = async () => {
      if (cancelled || inFlight || document.hidden) return;
      inFlight = true;
      setLoading(true);
      try {
        await loadTasks(
          (result, updating) => {
            if (!cancelled) {
              setData(result);
              if (!updating)
                writeSnapshot(cacheKey, withoutGamesScores(result));
              setCached(false);
              setError("");
            }
          },
          () => !cancelled,
        );
      } catch (cause) {
        if (!cancelled) {
          if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
            setData(null);
            setCached(false);
          }
          setError(
            cause instanceof Error
              ? cause.message
              : "Could not update your tasks. Try again.",
          );
        }
      } finally {
        inFlight = false;
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    const check = () => {
      if (!paused) void load();
    };
    const timer = window.setInterval(check, 60000);
    document.addEventListener("visibilitychange", check);
    window.addEventListener("online", check);
    return () => {
      cancelled = true;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("online", check);
    };
  }, [paused, refresh]);
  const previousFilters = useRef([tab, selected, search, sort]);
  useEffect(() => {
    const next = [tab, selected, search, sort];
    if (next.some((value, index) => value !== previousFilters.current[index]))
      setPage(0);
    previousFilters.current = next;
  }, [tab, selected, search, sort]);
  const gaps = todoHasGaps(data);
  const view = data?.views[tab];
  const canFilter = !!view?.rows.length || !!search;
  const config = todoTabs.find((item) => item.key === tab)!;
  const rows = visibleTodoRows(
    view?.rows || [],
    selected,
    search,
    sort,
    !!initialSearch && search === initialSearch,
  );
  const lastPage = Math.max(0, Math.ceil(rows.length / 12) - 1),
    currentPage = Math.min(page, lastPage);
  const groups = new Map<string, TodoRow[]>();
  rows.slice(currentPage * 12, (currentPage + 1) * 12).forEach((row) => {
    const key = row.clan_tag || "none";
    groups.set(key, [...(groups.get(key) || []), row]);
  });
  const accounts = data?.accounts || [];
  const filteredAccounts = accounts.filter((account) =>
    `${account.name} ${account.tag} ${account.current_clan_name || ""}`
      .toLocaleLowerCase()
      .includes(accountSearch.toLocaleLowerCase()),
  );
  const selectedCount =
    selected === null
      ? accounts.length
      : accounts.filter((account) => selected.includes(account.tag)).length;
  // Same account selection as the Cannot check tab count.
  const unreadableRows = (data?.views.private.rows || []).filter(
    (row) => selected === null || selected.includes(row.tag),
  );
  return (
    <div className="todo-workspace roster-ui">
      <div className="page-head todo-head">
        <h1>Tasks</h1>
        <button
          className="todo-check"
          aria-busy={loading || undefined}
          onClick={() => setRefresh((value) => value + 1)}
          disabled={loading}
        >
          <RefreshCw aria-hidden="true" size={16} />
          {loading ? "Checking…" : "Check now"}
        </button>
      </div>
      <div className="todo-refresh">
        <span role="status" className="todo-status">
          <span
            className={`status-dot ${data && !error && !gaps && !loading && !paused ? "active" : ""}`}
          />
          {cached
            ? error
              ? "Showing saved data · refresh failed"
              : "Showing saved data · checking for updates…"
            : loading
              ? "Checking linked accounts and clan activity…"
              : error
                ? "Refresh needs attention"
                : gaps
                  ? "Some activity could not be checked · try again shortly"
                  : data
                    ? `${paused ? "Paused · checked" : "Checked"} ${new Date(data.checked_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                    : "Loading your activity…"}
        </span>
        <button
          className="todo-icon-button"
          aria-pressed={paused}
          aria-label="Pause auto-refresh"
          title="Pause auto-refresh"
          onClick={() => setPaused((value) => !value)}
        >
          {paused ? (
            <Play aria-hidden="true" size={16} />
          ) : (
            <Pause aria-hidden="true" size={16} />
          )}
        </button>
        {onWars && (
          <button
            className="todo-wars-link"
            onClick={() => onWars(tab === "cwl" ? "cwl" : "war")}
          >
            War scores →
          </button>
        )}
      </div>
      {error && (
        <div className="notice error" role="alert">
          <div>
            {error}
            {data && (
              <small>Showing your last update. It may be out of date.</small>
            )}
          </div>
          <button onClick={() => setRefresh((value) => value + 1)}>
            Retry
          </button>
        </div>
      )}
      {!data && !error && (
        <div className="card todo-loading" role="status">
          <strong>Loading your tasks…</strong>
          <p>Checking your linked accounts and clans.</p>
        </div>
      )}
      {data && (
        <>
          <SectionTabs
            className="todo-tabs section-tabs--flow"
            label="Activity types"
            items={todoTabs.map((item) => {
              const activity = data.views[item.key];
              const count = visibleTodoRows(
                activity.rows,
                selected,
                search,
                "deadline",
                !!initialSearch && search === initialSearch,
              ).length;
              return {
                id: item.key,
                label: (
                  <>
                    <span aria-hidden="true">
                      <DashboardIcon name={item.icon} />
                    </span>
                    <strong>{item.label}</strong>
                    <small>
                      {activity.loading
                        ? "Checking…"
                        : !activity.ok
                          ? "Unavailable"
                          : activity.incomplete
                            ? count
                              ? `${count} · Partial`
                              : "Not checked"
                            : activity.unavailable
                              ? "Not active"
                              : `${count} account${count === 1 ? "" : "s"}`}
                    </small>
                  </>
                ),
              };
            })}
            value={tab}
            onChange={(next) => {
              setTab(next);
            }}
            revealSelection
          />
          <h2 className="todo-visually-hidden">{config.label}</h2>
          <div className="todo-toolbar">
            <button
              type="button"
              className="todo-chip"
              aria-expanded={pickerOpen}
              aria-controls="todo-account-panel"
              ref={accountsChip}
              onClick={() => setPickerOpen((open) => !open)}
            >
              {selected === null
                ? data.linked_account_count &&
                  accounts.length < data.linked_account_count
                  ? `${accounts.length} of ${data.linked_account_count} accounts`
                  : "All accounts"
                : `${selectedCount} account${selectedCount === 1 ? "" : "s"}`}
              <ChevronDown aria-hidden="true" size={16} />
            </button>
            {canFilter && (
              <label className="todo-chip todo-sort">
                <span className="todo-visually-hidden">Sort tasks</span>
                <select
                  name="todo-sort"
                  value={sort}
                  onChange={(event) => setSort(event.target.value)}
                >
                  <option value="deadline">Ends soonest</option>
                  <option value="th">Highest TH</option>
                  <option value="name">Name A–Z</option>
                </select>
              </label>
            )}
            {(canFilter || searchVisible) && (
              <button
                type="button"
                className="todo-icon-button"
                aria-label="Search tasks"
                aria-expanded={searchVisible}
                aria-controls={searchVisible ? "todo-search" : undefined}
                ref={searchButton}
                onClick={openSearch}
              >
                <Search aria-hidden="true" size={16} />
              </button>
            )}
          </div>
          {searchVisible && (
            <div className="todo-search-row" id="todo-search">
              <label className="todo-search">
                <span className="todo-visually-hidden">Search tasks</span>
                <Search aria-hidden="true" size={16} />
                <input
                  ref={searchInput}
                  type="search"
                  name="todo-search"
                  autoComplete="off"
                  spellCheck={false}
                  value={search}
                  onFocus={() => setSearchOpen(true)}
                  onChange={(event) => {
                    setSearchOpen(true);
                    setSearch(event.target.value);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") closeSearch();
                  }}
                  placeholder="Account, tag or clan…"
                />
              </label>
              <button
                type="button"
                className="todo-icon-button"
                aria-label="Clear and close search"
                onClick={closeSearch}
              >
                <X aria-hidden="true" size={16} />
              </button>
            </div>
          )}
          <div
            id="todo-account-panel"
            className="todo-account-picker"
            hidden={!pickerOpen}
          >
            <div className="todo-picker-tools">
              <label>
                Find linked accounts
                <input
                  type="search"
                  value={accountSearch}
                  onChange={(event) => setAccountSearch(event.target.value)}
                  placeholder="Account or clan name…"
                />
              </label>
              <button onClick={() => setSelected(null)}>All accounts</button>
              <button onClick={() => setSelected([])}>Clear</button>
            </div>
            <div className="todo-picker-list">
              {filteredAccounts.map((account) => (
                <label key={account.tag}>
                  <input
                    type="checkbox"
                    checked={
                      selected === null || selected.includes(account.tag)
                    }
                    onChange={(event) =>
                      setSelected((current) => {
                        const previous =
                          current === null
                            ? accounts.map((item) => item.tag)
                            : current;
                        return event.target.checked
                          ? [...new Set([...previous, account.tag])]
                          : previous.filter((tag) => tag !== account.tag);
                      })
                    }
                  />
                  <TownHallIcon level={account.town_hall} />
                  <span>
                    <strong>{account.name}</strong>
                    <small>{account.tag}</small>
                  </span>
                </label>
              ))}
              {!filteredAccounts.length && <p>No matching linked accounts.</p>}
            </div>
          </div>
          {tab === "cwl" && (
            <p className="todo-tab-note">
              Live CWL wars, separate from season signups.
            </p>
          )}
          {tab === "games" && view?.season ? (
            <ClanGamesSummary view={view} now={now} />
          ) : (
            (tab === "raid" ||
              tab === "games" ||
              (tab === "cwl" && rows.length === 0)) && (
              <TaskEventTimer kind={tab} now={now} />
            )
          )}
          {view && (
            <>
              <TodoActivityStatus
                view={view}
                hasRows={rows.length > 0}
                unreadable={tab === "war" ? unreadableRows.length : 0}
                onAffected={() => setTab("private")}
              />
              {view.loading ? (
                <div className="card todo-loading" role="status">
                  <strong>Checking {config.label.toLowerCase()}…</strong>
                  <p>
                    You can view other activities while this check finishes.
                  </p>
                </div>
              ) : !rows.length &&
                (!view.ok || !!view.incomplete) ? null : !accounts.length ? (
                <div className="card empty">
                  <h3>No linked accounts to show</h3>
                  <p>
                    Use ClashKing’s /link command in Discord, then check again.
                  </p>
                </div>
              ) : !rows.length ? (
                <div className="card empty">
                  <h3>
                    {!view.ok || view.incomplete
                      ? "Check in-game"
                      : selectedCount === 0
                        ? "Select accounts to see their tasks"
                        : "Nothing to show here"}
                  </h3>
                  <p>
                    {todoEmptyText(view, tab, selected !== null || !!search)}
                  </p>
                </div>
              ) : (
                <div className="todo-clan-list">
                  {[...groups.entries()].map(([key, members]) => (
                    <section className="todo-clan" key={key}>
                      <header>
                        <Badge url={members[0].badge_url} />
                        <div>
                          <h3>{clanLabel(members[0])}</h3>
                          {tab === "war" && members[0].fwa_outcome && (
                            <div
                              className={`todo-fwa ${members[0].fwa_outcome.status}`}
                            >
                              <strong>
                                {
                                  {
                                    win: "FWA WIN",
                                    lose: "FWA LOSE",
                                    blacklisted: "BLACKLISTED",
                                    unknown: "FWA Unknown",
                                  }[members[0].fwa_outcome.status]
                                }
                              </strong>
                              {members[0].fwa_outcome.opponent && (
                                <span>
                                  vs {members[0].fwa_outcome.opponent}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                        {key !== "none" && (
                          <a
                            href={clanDeepLink(key)}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label={`Open ${clanLabel(members[0])} in Clash of Clans`}
                          >
                            Open ↗
                          </a>
                        )}
                      </header>
                      {members.map((row, index) => (
                        <TodoTaskCard
                          key={`${row.tag}-${index}`}
                          row={row}
                          kind={tab}
                          now={now}
                        />
                      ))}
                    </section>
                  ))}
                </div>
              )}
              {lastPage > 0 && (
                <nav className="todo-pagination" aria-label="Activity pages">
                  <button
                    disabled={currentPage === 0}
                    onClick={() => setPage(currentPage - 1)}
                  >
                    ← Previous
                  </button>
                  <span>
                    {currentPage + 1} / {lastPage + 1}
                  </span>
                  <button
                    disabled={currentPage === lastPage}
                    onClick={() => setPage(currentPage + 1)}
                  >
                    Next →
                  </button>
                </nav>
              )}
              {tab === "war" && !view.loading && unreadableRows.length > 0 && (
                <TodoPrivateNote
                  rows={unreadableRows}
                  onView={() => setTab("private")}
                />
              )}
            </>
          )}
          {tab === "cwl" && rows.length > 0 && (
            <TaskEventTimer kind="cwl" now={now} />
          )}
        </>
      )}
      <p className="todo-freshness">
        Game data can be a few minutes late after an attack.
      </p>
      <PushReminders
        key={userId}
        accounts={accounts}
        accountsComplete={
          !!data &&
          !loading &&
          (!data.linked_account_count ||
            accounts.length >= data.linked_account_count)
        }
      />
    </div>
  );
}
