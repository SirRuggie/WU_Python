import DiscordIdentity from "./DiscordIdentity";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import DashboardIcon from "./DashboardIcon";
import { api, ApiError } from "./api";
import type { Ticket } from "./TicketBrowser";
type Message = {
  id: string;
  author: string;
  at: string | null;
  edited: boolean;
  text: string;
  attachments: { name: string; url: string }[];
  bot: boolean;
};
type Conversation = {
  ticket: Ticket;
  messages: Message[];
  older: string | null;
  discord_url: string;
  archived: boolean;
  checked_at: number;
};
const statusName = (value: string) =>
  ({ open: "Open", approved: "Approved", denied: "Denied", closed: "Closed" })[
    value
  ] || value;
const when = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "Date unavailable";
export default function TicketConversation({
  ticket,
  onBack,
}: {
  ticket: Ticket;
  onBack: () => void;
}) {
  const [space, setSpace] = useState("applicant"),
    [before, setBefore] = useState(""),
    [data, setData] = useState<Conversation | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0),
    [search, setSearch] = useState(""),
    [paused, setPaused] = useState(false),
    [denied, setDenied] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [ticket.id]);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const readerKey = useRef("");
  useEffect(() => {
    let alive = true,
      inFlight = false;
    const key = `${ticket.id}:${space}:${before}`;
    if (readerKey.current !== key) {
      setData(null);
      setSearch("");
      readerKey.current = key;
    }
    setError("");
    let accessLost = false;
    const load = async () => {
      if (!alive || inFlight || accessLost) return;
      inFlight = true;
      setBusy(true);
      try {
        const result = await api<Conversation>(
          `/manage/tickets/${encodeURIComponent(ticket.id)}/messages?${new URLSearchParams({ space, before })}`,
        );
        if (alive) {
          setData(result);
          setDenied(false);
          setError("");
        }
      } catch (e) {
        if (alive) {
          if (e instanceof ApiError && [401, 403, 404].includes(e.status)) {
            setData(null);
            setDenied(true);
            accessLost = true;
          }
          setError(e instanceof Error ? e.message : "Could not load messages.");
        }
      } finally {
        inFlight = false;
        if (alive) setBusy(false);
      }
    };
    void load();
    const timer = setInterval(() => {
      if (!pausedRef.current && !before && !document.hidden) void load();
    }, 30000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [ticket.id, space, before, reload]);
  if (denied)
    return (
      <section className="ticket-browser">
        <button onClick={onBack}>← Back to tickets</button>
        <h1>Ticket unavailable</h1>
        <p className="notice error" role="alert">
          {error || "Checking access…"}
        </p>
        <button disabled={busy} onClick={() => setReload((n) => n + 1)}>
          Retry loading messages
        </button>
      </section>
    );
  const messages =
    data?.messages.filter((m) =>
      (
        m.author +
        " " +
        m.text +
        " " +
        m.attachments.map((a) => a.name).join(" ")
      )
        .toLocaleLowerCase()
        .includes(search.toLocaleLowerCase()),
    ) || [];
  return (
    <section className="ticket-browser">
      <button onClick={onBack}>← Back to tickets</button>
      <div className="page-head ticket-heading">
        <div>
          <p className="eyebrow">
            {ticket.kind.toUpperCase()} · {statusName(ticket.status)} · Read
            only
          </p>
          <h1 ref={heading} tabIndex={-1}>
            #{ticket.number} · {ticket.name}
          </h1>
          <DiscordIdentity
            userId={ticket.user_id}
            displayName={ticket.name}
            resolvedMember={null}
          />
          <p>Reply and handle this application in Discord.</p>
          <small>Opened {when(ticket.created_at)}</small>
          {ticket.flags.length > 0 && (
            <div className="ticket-flag-details" aria-label="Applicant flags">
              <h2>Applicant flags</h2>
              {ticket.flags.map((item, index) => (
                <p key={`${item.kind}-${index}`}>
                  <strong>{item.label}</strong>
                  {item.reason ? ` · ${item.reason}` : ""}
                </p>
              ))}
            </div>
          )}
        </div>
      </div>
      <div
        className="ticket-conversation-tabs"
        role="group"
        aria-label="Ticket conversation"
      >
        <button
          aria-pressed={space === "applicant"}
          onClick={() => {
            setSpace("applicant");
            setBefore("");
          }}
        >
          Applicant
        </button>
        <button
          aria-pressed={space === "staff"}
          onClick={() => {
            setSpace("staff");
            setBefore("");
          }}
        >
          Staff
        </button>
      </div>
      <div className="ticket-reader-tools">
        <button disabled={busy} onClick={() => setReload((n) => n + 1)}>
          Refresh messages
        </button>
        {data && (
          <a
            className="button"
            href={data.discord_url}
            target="_blank"
            rel="noreferrer"
          >
            Open conversation in Discord ↗
          </a>
        )}
      </div>
      <p className="small">
        {before
          ? "Reading older messages. Automatic refresh is paused."
          : paused
            ? "Automatic refresh paused."
            : "New messages refresh every 30 seconds."}
        {data
          ? ` Updated ${new Date(data.checked_at * 1000).toLocaleTimeString()}.`
          : ""}
      </p>
      {error && (
        <p className="notice error" role="alert">
          {error}
          {data ? " Showing the last update." : ""}
          <button disabled={busy} onClick={() => setReload((n) => n + 1)}>
            Retry loading messages
          </button>
        </p>
      )}
      {busy && !data && <p role="status">Loading conversation…</p>}
      {data && (
        <>
          <details className="ticket-date-filter">
            <summary>
              Find messages &amp; refresh options
              {search ? " · search active" : ""}
            </summary>
            <div>
              {" "}
              <label>
                Find in these {data.messages.length} messages
                <input
                  type="search"
                  placeholder="Name or words in this page"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </label>{" "}
              <label>
                <input
                  type="checkbox"
                  checked={paused}
                  onChange={(e) => setPaused(e.target.checked)}
                />
                Pause refresh
              </label>
            </div>
          </details>
          <nav className="ticket-pages" aria-label="Message pages">
            <button
              disabled={busy || !data.older}
              onClick={() => setBefore(data.older || "")}
            >
              Older messages
            </button>
            {before && (
              <button disabled={busy} onClick={() => setBefore("")}>
                Latest messages
              </button>
            )}
          </nav>
          <div className="ticket-messages">
            {messages.map((m) => (
              <article className="ticket-message" key={m.id}>
                <header>
                  <strong>
                    {m.author}
                    {m.bot ? " · Bot" : ""}
                  </strong>
                  <small>
                    {when(m.at)}
                    {m.edited ? " · Edited" : ""}
                  </small>
                </header>
                {m.text ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    skipHtml
                    components={{
                      a: ({ children, href }) => (
                        <a href={href} target="_blank" rel="noreferrer">
                          {children}
                        </a>
                      ),
                      img: ({ src, alt }) => (
                        <a
                          href={typeof src === "string" ? src : undefined}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {alt || "View image"} ↗
                        </a>
                      ),
                    }}
                  >
                    {m.text}
                  </ReactMarkdown>
                ) : (
                  !m.attachments.length && (
                    <p className="small">
                      System message or content unavailable. Open in Discord to
                      check.
                    </p>
                  )
                )}
                {m.attachments.length > 0 && (
                  <ul className="ticket-attachments">
                    {m.attachments.map((a, i) => (
                      <li key={i}>
                        <a href={a.url} target="_blank" rel="noreferrer">
                          <DashboardIcon name="attachment" /> {a.name} ↗
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </article>
            ))}
            {!messages.length && (
              <p>
                {search
                  ? "No matches in these messages."
                  : "No messages returned. If Discord shows messages, ask an owner to check the bot’s Read Message History and Message Content access."}
              </p>
            )}
          </div>
          <p className="small">
            Attachments open from Discord. Deleted messages and threads may no
            longer be available.
          </p>
        </>
      )}
    </section>
  );
}
