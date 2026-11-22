import { searchInputProps } from "./inputProps";
import EmptyState from "./EmptyState";
import { formatDateTime, formatNumber } from "./format";
import LoadError from "./LoadError";
import CwlPageHeader from "./CwlPageHeader";
import RefreshControl, { useRefreshTime } from "./RefreshControl";
import { ArrowRight, Shield, UserPlus, Users } from "lucide-react";
import DiscordIdentity, { discordIdentityName } from "./DiscordIdentity";
import TicketConversation from "./TicketConversation";
import { dashboardPath, dashboardTarget } from "./dashboardHistory";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import "./TicketBrowser.css";
import { parsePageParam, replacePageParam } from "./pageUrlState";
import ActionPanel from "./ActionPanel";
import SectionTabs from "./SectionTabs";
import ListToolbar from "./rosterUi/ListToolbar";
import FiltersTrigger from "./rosterUi/FiltersTrigger";
export type Ticket = {
  id: string;
  number: number;
  name: string;
  user_id: string;
  kind: string;
  account_clan?: "main" | "fwa" | null;
  status: string;
  created_at: string | null;
  flags: { kind: string; label: string; reason: string }[];
};
const ticketTypeName = (kind: string, accountClan?: string | null) =>
  kind === "account" && (accountClan === "main" || accountClan === "fwa")
    ? `Add account · ${accountClan === "main" ? "Main" : "FWA"}`
    : {
        main: "Recruit",
        fwa: "Recruit",
        account: "Add account",
        staff: "Contact staff",
      }[kind] || "Ticket";
const ticketIcon = (kind: string) =>
  kind === "staff" ? Shield : kind === "account" ? UserPlus : Users;
const initialTicketType = () => {
  const params = new URLSearchParams(window.location.search);
  const value = params.get("type") || params.get("kind") || "all";
  return ["all", "main", "fwa", "recruit", "account", "staff"].includes(value)
    ? value
    : "all";
};
const statusName = (value: string) =>
  ({ open: "Open", approved: "Approved", denied: "Denied", closed: "Closed" })[
    value
  ] || value;
const when = (value: string | null) =>
  value
    ? formatDateTime(new Date(value), { timeZone: "UTC" })
    : "Date unavailable";
export default function TicketBrowser() {
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filtersTrigger, setFiltersTrigger] = useState<HTMLElement | null>(
    null,
  );
  const [status, setStatus] = useState(() =>
      parsePageParam("tickets", "status", window.location.search),
    ),
    [kind, setKind] = useState(() => initialTicketType()),
    [flag, setFlag] = useState("all"),
    [search, setSearch] = useState(""),
    [query, setQuery] = useState(""),
    [from, setFrom] = useState(""),
    [to, setTo] = useState(""),
    [page, setPage] = useState(1),
    [tickets, setTickets] = useState<Ticket[]>([]),
    [more, setMore] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0),
    [selected, setSelected] = useState<Ticket | null>(null);
  const [noAccess, setNoAccess] = useState(false);
  const [allowedTypes, setAllowedTypes] = useState<string[] | null>(null);
  const [readerId, setReaderId] = useState(
    () =>
      dashboardTarget(window.location.search, window.location.pathname)
        .ticket || "",
  );
  const readerBackPending = useRef(false);
  const readerUrl = (id: string) =>
    dashboardPath({
      ...dashboardTarget(window.location.search, window.location.pathname),
      view: "tickets",
      season: "",
      ticket: id,
    });
  const listUrl = () => {
    const url = new URL(window.location.href);
    url.searchParams.delete("ticket");
    return url.pathname + url.search + url.hash;
  };
  const restoreReaderLocation = () => {
    const next =
      dashboardTarget(window.location.search, window.location.pathname)
        .ticket || "";
    readerBackPending.current = false;
    setReaderId(next);
    setSelected((current) => (current?.id === next ? current : null));
    if (!next) {
      returnReady.current = false;
      setBusy(true);
    }
  };
  useEffect(() => {
    window.addEventListener("popstate", restoreReaderLocation);
    return () => window.removeEventListener("popstate", restoreReaderLocation);
  }, []);
  const returnTicket = useRef<string | null>(null);
  const returnReady = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const ticketButtons = useRef(new Map<string, HTMLAnchorElement>());
  useEffect(() => {
    if (selected || busy || !returnReady.current || !returnTicket.current)
      return;
    (
      ticketButtons.current.get(returnTicket.current) || heading.current
    )?.focus();
    returnTicket.current = null;
    returnReady.current = false;
  }, [selected, busy, tickets, error]);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);
  useEffect(() => {
    if (readerId) return;
    let alive = true;
    setBusy(true);
    setError("");
    setNoAccess(false);
    setTickets([]);
    const params = new URLSearchParams({
      status,
      type: kind,
      flag,
      q: query,
      from,
      to,
      page: String(page),
    });
    api<{ tickets: Ticket[]; has_more: boolean; allowed_types?: string[] }>(
      `/manage/tickets?${params}`,
    )
      .then((result) => {
        if (alive) {
          setTickets(result.tickets);
          setMore(result.has_more);
          setAllowedTypes(
            result.allowed_types || ["main", "fwa", "account", "staff"],
          );
        }
      })
      .catch((e) => {
        if (alive) {
          if (e instanceof ApiError && e.status === 403 && kind !== "all") {
            // A stale forbidden scope can coexist with access to other types.
            // One All read distinguishes that case from a global denial.
            setKind("all");
            setPage(1);
            replacePageParam("tickets", "type", "all");
            return;
          }
          setError(e.message);
          setNoAccess(e instanceof ApiError && e.status === 403);
          setMore(false);
        }
      })
      .finally(() => {
        if (alive) {
          returnReady.current = true;
          setBusy(false);
        }
      });
    return () => {
      alive = false;
    };
  }, [readerId, status, kind, flag, query, from, to, page, reload]);
  const updatedAt = useRefreshTime(busy, true, error);
  const extraFilters = Number(flag !== "all") + Number(!!from) + Number(!!to);
  const filterCount = Number(status !== "open") + extraFilters;
  const statusLabel = `${status === "all" ? "All" : statusName(status)} tickets`;
  const scopeItems = [
    ...(allowedTypes?.some((type) => type === "main" || type === "fwa")
      ? [{ id: "recruit", label: "Recruits" }]
      : []),
    ...(allowedTypes?.includes("account")
      ? [{ id: "account", label: "Accounts" }]
      : []),
    ...(allowedTypes?.includes("staff")
      ? [{ id: "staff", label: "Staff" }]
      : []),
  ];
  const scopeValue = kind === "main" || kind === "fwa" ? "recruit" : kind;
  const displayScope =
    scopeValue === "all" && scopeItems.length === 1
      ? scopeItems[0].id
      : scopeValue;
  const scopeNoun =
    displayScope === "staff"
      ? "staff requests"
      : displayScope === "account"
        ? "account requests"
        : displayScope === "recruit"
          ? "recruit applications"
          : "tickets";
  const clearFilters = () => {
    setSearch("");
    setQuery("");
    setStatus("open");
    setKind("all");
    replacePageParam("tickets", "status", "open");
    replacePageParam("tickets", "type", "all");
    setFlag("all");
    setFrom("");
    setTo("");
    setPage(1);
  };
  if (readerId)
    return (
      <TicketConversation
        ticket={
          selected?.id === readerId
            ? selected
            : {
                id: readerId,
                number: 0,
                name: "",
                user_id: "",
                kind: "",
                status: "",
                created_at: null,
                flags: [],
              }
        }
        onBack={() => {
          if (readerBackPending.current) return;
          returnTicket.current = readerId;
          if (window.history.state?.wuTicketReader === readerId) {
            readerBackPending.current = true;
            window.history.back();
          } else {
            const { wuTicketReader: _reader, ...state } =
              window.history.state || {};
            window.history.replaceState(state, "", listUrl());
            restoreReaderLocation();
          }
        }}
      />
    );
  if (noAccess)
    return (
      <section className="ticket-browser">
        <CwlPageHeader
          title={
            <h1 ref={heading} tabIndex={-1}>
              Tickets
            </h1>
          }
        />
        <p role="status">You do not have access to tickets.</p>
      </section>
    );
  return (
    <section className="ticket-browser">
      <CwlPageHeader
        title={
          <h1 ref={heading} tabIndex={-1}>
            Tickets
          </h1>
        }
        description="Review recruit applications and member requests. Reply or make decisions in Discord."
      >
        <RefreshControl
          updatedAt={updatedAt}
          busy={busy}
          showRefresh={!error}
          onRefresh={() => setReload((n) => n + 1)}
        />
      </CwlPageHeader>
      <div className="ticket-filters">
        <label>
          Find a ticket
          <input
            {...searchInputProps}
            type="search"
            placeholder="Member, ticket # or player tag"
            maxLength={80}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </div>
      <ListToolbar
        className="ticket-toolbar"
        scope={
          scopeItems.length > 1 ? (
            <SectionTabs
              mode="segmented"
              label="Ticket type"
              items={[{ id: "all", label: "All" }, ...scopeItems]}
              value={scopeValue}
              onChange={(next) => {
                setKind(next);
                replacePageParam("tickets", "type", next);
                setPage(1);
              }}
            />
          ) : undefined
        }
        filters={
          <FiltersTrigger
            className="ticket-filters-trigger"
            count={filterCount}
            open={filtersOpen}
            onClick={(event) => {
              setFiltersTrigger(event.currentTarget);
              setFiltersOpen(true);
            }}
          />
        }
      />
      {filtersOpen && (
        <ActionPanel
          title="Filter tickets"
          trigger={filtersTrigger}
          onClose={() => setFiltersOpen(false)}
        >
          <div className="ticket-filter-fields">
            <label>
              Status
              <select
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value);
                  replacePageParam("tickets", "status", event.target.value);
                  setPage(1);
                }}
              >
                <option value="open">Open tickets</option>
                <option value="all">All tickets</option>
                <option value="approved">Approved</option>
                <option value="denied">Denied</option>
                <option value="closed">Closed tickets</option>
              </select>
            </label>
            <label>
              Applicant flag
              <select
                value={flag}
                onChange={(e) => {
                  setFlag(e.target.value);
                  setPage(1);
                }}
              >
                <option value="all">All flags</option>
                <option value="blacklisted">Blacklisted</option>
                <option value="denied_before">Previously denied</option>
                <option value="not_loyal">Not loyal to WU</option>
                <option value="ghosted">Ghosted</option>
                <option value="flew_the_coop">Flew the Coop</option>
              </select>
            </label>
            <label>
              From
              <input
                type="date"
                value={from}
                onChange={(e) => {
                  setFrom(e.target.value);
                  setPage(1);
                }}
              />
            </label>
            <label>
              To
              <input
                type="date"
                value={to}
                onChange={(e) => {
                  setTo(e.target.value);
                  setPage(1);
                }}
              />
            </label>
            <small>Dates use UTC.</small>
          </div>
        </ActionPanel>
      )}
      <div className="ticket-list-summary">
        <span>
          {statusLabel}
          {busy
            ? " · Loading…"
            : error
              ? ""
              : ` · ${formatNumber(tickets.length)} on this page`}
        </span>
        {(search ||
          status !== "open" ||
          kind !== "all" ||
          extraFilters > 0) && (
          <button onClick={clearFilters}>Clear filters</button>
        )}
      </div>
      <LoadError
        message={error}
        onRetry={() => setReload((n) => n + 1)}
        busy={busy}
      />
      {busy ? (
        <p role="status">Loading tickets…</p>
      ) : !error && !tickets.length ? (
        <EmptyState
          title={`No ${status === "open" ? "open " : ""}${scopeNoun}`}
          line="Try another name, status or date."
          action={<button onClick={clearFilters}>Clear filters</button>}
        />
      ) : (
        <div className="ticket-list">
          {tickets.map((t) => (
            <article className="ticket-row" key={t.id}>
              <div>
                <div className="ticket-name-line">
                  <strong>#{t.number}</strong>
                  <DiscordIdentity
                    userId={t.user_id}
                    displayName={t.name}
                    resolvedMember={null}
                    variant="compact"
                    contact={false}
                  />
                  {t.flags.length > 0 && (
                    <ul className="ticket-flags" aria-label="Applicant flags">
                      {t.flags.map((item, index) => (
                        <li key={`${item.kind}-${index}`}>{item.label}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <small className="ticket-type-line">
                  {(() => {
                    const Icon = ticketIcon(t.kind);
                    return <Icon size={16} aria-hidden="true" />;
                  })()}
                  {ticketTypeName(t.kind, t.account_clan)} ·{" "}
                  {statusName(t.status)} · Opened {when(t.created_at)}
                </small>
              </div>
              <a
                href={readerUrl(t.id)}
                className="ticket-read"
                ref={(node) => {
                  if (node) ticketButtons.current.set(t.id, node);
                  else ticketButtons.current.delete(t.id);
                }}
                aria-label={`Read ${discordIdentityName(t.user_id, null, t.name) || "Discord member unavailable"} #${t.number}, ${ticketTypeName(t.kind, t.account_clan)}`}
                onClick={(event) => {
                  if (
                    event.button !== 0 ||
                    event.metaKey ||
                    event.ctrlKey ||
                    event.shiftKey ||
                    event.altKey
                  )
                    return;
                  event.preventDefault();
                  returnTicket.current = t.id;
                  window.history.pushState(
                    { ...window.history.state, wuTicketReader: t.id },
                    "",
                    readerUrl(t.id),
                  );
                  setSelected(t);
                  setReaderId(t.id);
                }}
              >
                Read <ArrowRight size={16} aria-hidden="true" />
              </a>
            </article>
          ))}
        </div>
      )}
      {!busy && !error && (page > 1 || more) && (
        <nav className="ticket-pages" aria-label="Ticket pages">
          <button disabled={page === 1} onClick={() => setPage((n) => n - 1)}>
            Previous
          </button>
          <span>Page {page}</span>
          <button disabled={!more} onClick={() => setPage((n) => n + 1)}>
            Next
          </button>
        </nav>
      )}
    </section>
  );
}
