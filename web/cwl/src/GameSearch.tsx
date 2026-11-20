import { useEffect, useId, useRef, useState } from "react";
import { api, ApiError, type Account, type Clan, type Session } from "./api";
import type { GameResult, GameSearchResponse } from "./dashboardSearch";
import {
  familyGameResults,
  mergeGameResults,
  gameTag,
} from "./dashboardSearch";
import DashboardIcon from "./DashboardIcon";
import DashboardLink from "./DashboardLink";
import { dashboardPath } from "./dashboardHistory";
import TownHallIcon from "./TownHallIcon";
import PlayerClanDetailsDialog, {
  safeClanBadgeUrl,
} from "./PlayerClanDetailsDialog";
import MemberDetailActivity from "./MemberDetailActivity";
import EmptyState from "./EmptyState";
import LoadError from "./LoadError";
import FilterChips from "./FilterChips";
import "./GameSearch.css";

type Kind = "all" | "player" | "clan";
export default function GameSearch({
  session,
  onTasks,
  query: controlled,
  onQuery,
  kind: controlledKind,
  onKind,
  compact = false,
  accounts = [],
  family = [],
  familyBusy = false,
  familyError = "",
  onRetryFamily,
  page: controlledPage,
  onPage,
}: {
  session: Session;
  onTasks: (tag: string) => void;
  query?: string;
  onQuery?: (query: string) => void;
  kind?: Kind;
  onKind?: (kind: Kind) => void;
  compact?: boolean;
  accounts?: Account[];
  family?: Clan[];
  familyBusy?: boolean;
  familyError?: string;
  onRetryFamily?: () => void;
  page?: number;
  onPage?: (page: number) => void;
}) {
  const id = useId();
  const [local, setLocal] = useState("");
  const [localKind, setLocalKind] = useState<Kind>("all");
  const query = controlled ?? local,
    kind = controlledKind ?? localKind;
  const [payload, setPayload] = useState<GameSearchResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<GameResult | null>(null);
  const generation = useRef(0),
    timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requested = useRef<string | null>(null);
  const key = query.trim().replace(/\s+/g, " ").toLowerCase();
  const current = useRef(key);
  current.current = key;
  async function search(force = false) {
    if (timer.current) clearTimeout(timer.current);
    const value = current.current;
    if (!value || (!force && requested.current === value)) return;
    requested.current = value;
    const own = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const result = await api<GameSearchResponse>(
        `/search?q=${encodeURIComponent(value)}`,
      );
      if (generation.current !== own || current.current !== value) return;
      setPayload(result);
    } catch (failure) {
      if (generation.current !== own || current.current !== value) return;
      requested.current = null;
      setPayload(null);
      setError(
        failure instanceof ApiError && failure.status === 429
          ? "Too many searches. Wait a minute."
          : failure instanceof Error
            ? failure.message
            : "Search could not load.",
      );
    } finally {
      if (generation.current === own) setBusy(false);
    }
  }
  useEffect(() => {
    generation.current++;
    requested.current = null;
    setPayload(null);
    setDetail(null);
    setError("");
    setBusy(false);
    if (key) timer.current = setTimeout(() => void search(), 350);
    return () => {
      generation.current++;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [key, session.user.id]);
  const familyRows = familyGameResults(accounts, family, query);
  const all = mergeGameResults(familyRows, payload?.results || []);
  const [localPage, setLocalPage] = useState(0);
  const visible = all.filter((row) => kind === "all" || row.kind === kind);
  const lastPage = Math.max(0, Math.ceil(visible.length / 20) - 1);
  const currentPage = Math.min(controlledPage ?? localPage, lastPage);
  useEffect(() => setLocalPage(0), [key, kind]);
  return (
    <section
      className={`game-search${compact ? " game-search--home" : ""}`}
      aria-label="Player and clan search"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void search();
        }}
      >
        <label className="global-search-field" htmlFor={id}>
          <DashboardIcon name="search" />
          <span className="sr-only">Search your players and clans</span>
          <input
            id={id}
            type="search"
            maxLength={40}
            placeholder="Search your players and clans"
            value={query}
            onChange={(event) => {
              const next = event.target.value;
              if (
                next.trim().replace(/\s+/g, " ").toLowerCase() !==
                current.current
              ) {
                generation.current++;
                requested.current = null;
                setPayload(null);
                setDetail(null);
                setBusy(false);
                setError("");
              }
              (onQuery || setLocal)(next);
            }}
          />
        </label>
        <button
          type="submit"
          disabled={busy || !key}
          aria-busy={busy || undefined}
        >
          Search
        </button>
      </form>
      {key && (
        <FilterChips
          label="Search result type"
          options={(["all", "player", "clan"] as const).map((value) => ({
            value,
            label:
              value === "all"
                ? "All"
                : value === "player"
                  ? "Players"
                  : "Clans",
            count: all.filter((row) => value === "all" || row.kind === value)
              .length,
          }))}
          value={kind}
          onChange={(value) => (onKind || setLocalKind)(value)}
          variant="pill"
          role="group"
        />
      )}
      {busy && <p role="status">Searching…</p>}
      {familyBusy && (
        <p role="status">Loading your linked accounts and family clans…</p>
      )}
      <LoadError
        message={[familyError, error, ...(payload?.errors || [])].filter(
          Boolean,
        )}
        onRetry={() => {
          onRetryFamily?.();
          return search(true);
        }}
        busy={busy}
        retryContext="player and clan search"
      />
      {(!gameTag(query) &&
      key &&
      !familyBusy &&
      !familyRows.some((row) => row.kind === "player")
        ? [
            "Player names match family accounts only. Search by tag to find any player.",
          ]
        : []
      ).map((note) => (
        <p className="muted" key={note}>
          {note}
        </p>
      ))}
      {!busy &&
        !familyBusy &&
        !familyError &&
        !error &&
        !payload?.errors?.length &&
        ((!key && !compact) || (payload && !visible.length)) && (
          <EmptyState
            title={key ? "No matches" : "Search players and clans"}
            line={
              key
                ? "Try a player tag or a clan name with at least 3 characters."
                : "Enter a player tag or clan name."
            }
          />
        )}
      {payload && !busy && (
        <p role="status">
          {visible.length} available result{visible.length === 1 ? "" : "s"}
        </p>
      )}
      <div className="search-results">
        {visible.slice(currentPage * 20, (currentPage + 1) * 20).map((row) => (
          <article className="search-result" key={`${row.kind}:${row.tag}`}>
            {row.kind === "player" ? (
              <TownHallIcon level={row.town_hall ?? null} />
            ) : safeClanBadgeUrl(row.badge_url) ? (
              <img
                src={safeClanBadgeUrl(row.badge_url)!}
                alt=""
                width={40}
                height={40}
                referrerPolicy="no-referrer"
              />
            ) : (
              <DashboardIcon name="shield" />
            )}
            <button
              className="game-search-open"
              onClick={() => setDetail(row)}
              aria-label={`${row.kind === "player" ? "Player" : "Clan"} details for ${row.name}`}
            >
              <strong>{row.name}</strong>
              <small>
                {row.tag} · {row.kind === "player" ? "Player" : "Clan"} ·{" "}
                {row.source === "family" ? "Family" : "Clash"}
              </small>
            </button>
            {row.source === "family" &&
              (row.kind === "player"
                ? accounts.some((item) => item.tag === row.tag)
                : accounts.some(
                    (item) => item.current_clan_tag === row.tag,
                  )) && (
                <DashboardLink
                  href={dashboardPath({
                    view: "todo",
                    season: "",
                    activityFilter: row.tag,
                  })}
                  onNavigate={() => onTasks(row.tag)}
                  aria-label={`Open tasks for ${row.name}`}
                >
                  Open tasks
                </DashboardLink>
              )}
          </article>
        ))}
      </div>
      {lastPage > 0 && (
        <nav aria-label="Search pages">
          <button
            disabled={currentPage === 0}
            onClick={() => (onPage || setLocalPage)(currentPage - 1)}
          >
            Previous
          </button>
          <span>
            Page {currentPage + 1} of {lastPage + 1}
          </span>
          <button
            disabled={currentPage === lastPage}
            onClick={() => (onPage || setLocalPage)(currentPage + 1)}
          >
            Next
          </button>
        </nav>
      )}
      {detail && (
        <SearchDetails
          accounts={accounts}
          family={family}
          familyFreshness={
            familyBusy ? "partial" : familyError ? "unavailable" : "current"
          }
          onDenied={() => {
            generation.current++;
            setPayload(null);
            setDetail(null);
            setError("Your dashboard access changed. Sign in again.");
          }}
          key={`${detail.kind}:${detail.tag}`}
          row={detail}
          session={session}
          onClose={() => setDetail(null)}
        />
      )}
    </section>
  );
}

function SearchDetails({
  row,
  session,
  onClose,
  onDenied,
  accounts,
  family,
  familyFreshness,
}: {
  row: GameResult;
  session: Session;
  onClose: () => void;
  onDenied: () => void;
  accounts: Account[];
  family: Clan[];
  familyFreshness: "current" | "partial" | "unavailable";
}) {
  const linked = accounts.find((account) => account.tag === row.tag);
  const directory = family.find((clan) => clan.tag === row.tag);
  const activity =
    row.kind === "player"
      ? !!linked
      : accounts.some((account) => account.current_clan_tag === row.tag);
  const familyAllowed = row.source === "family" && (activity || !!directory);
  const [data, setData] = useState(row),
    [busy, setBusy] = useState(true),
    [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (familyAllowed) {
      setData(row);
      setBusy(false);
      setError("");
      return;
    }
    let active = true;
    setBusy(true);
    setError("");
    void api<GameResult>(
      `/search/details?kind=${row.kind}&tag=${encodeURIComponent(row.tag)}`,
    )
      .then(
        (result) => {
          if (active) setData({ ...result, source: row.source });
        },
        (failure) => {
          if (
            active &&
            failure instanceof ApiError &&
            [401, 403].includes(failure.status)
          ) {
            onDenied();
            return;
          }
          if (active)
            setError(
              failure instanceof ApiError && failure.status === 429
                ? "Too many searches. Wait a minute."
                : failure instanceof Error
                  ? failure.message
                  : "Details could not load.",
            );
        },
      )
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [row.kind, row.tag, attempt, familyAllowed]);
  const children = (
    <>
      <LoadError
        message={error}
        onRetry={() => setAttempt((value) => value + 1)}
        busy={busy}
        retryContext="public game details"
      />
      {familyAllowed && activity && (
        <MemberDetailActivity
          target={row.kind}
          tag={row.tag}
          clanTag={row.clan_tag}
          onDenied={onDenied}
        />
      )}
    </>
  );
  const common = {
    freshness: familyAllowed
      ? familyFreshness
      : busy
        ? ("partial" as const)
        : error
          ? ("unavailable" as const)
          : ("current" as const),
    publicData: {
      ...data,
      source: familyAllowed ? ("family" as const) : ("clash" as const),
    },
    onClose,
    returnFocusFallbackId: "dashboard-main",
  };
  if (row.kind === "player") {
    const account: Account = {
      tag: data.tag,
      name: data.name,
      town_hall: data.town_hall ?? null,
      current_clan_tag: data.clan_tag ?? null,
      current_clan_name: data.clan_name ?? null,
      verified: false,
      lazy_eligible: false,
      lazy_ineligible_reason: null,
      family_clan_status: "unknown",
    };
    return (
      <PlayerClanDetailsDialog
        {...common}
        kind="player"
        account={familyAllowed && linked ? linked : account}
        session={familyAllowed && linked ? session : undefined}
      >
        {children}
      </PlayerClanDetailsDialog>
    );
  }
  return (
    <PlayerClanDetailsDialog
      {...common}
      kind="clan"
      tag={data.tag}
      name={data.name}
      badgeUrl={data.badge_url}
      clan={familyAllowed ? directory : undefined}
      linkedAccounts={familyAllowed ? accounts : undefined}
    >
      {children}
    </PlayerClanDetailsDialog>
  );
}
