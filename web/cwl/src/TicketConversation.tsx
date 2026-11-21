import { searchInputProps } from "./inputProps";
import RefreshControl from "./RefreshControl";
import LoadError from "./LoadError";
import { formatDateTime } from "./format";
import SectionTabs, { SectionTabPanel } from "./SectionTabs";
import CwlPageHeader from "./CwlPageHeader";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
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
  value
    ? formatDateTime(new Date(value), { timeZone: "UTC" })
    : "Date unavailable";
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
  const currentTicket = data?.ticket || ticket;
  const identityReady = currentTicket.number > 0;
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [ticket.id]);
  const refreshRead = useRef<() => void>(() => {});
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
        if (
          !Array.isArray(result.messages) ||
          (result.ticket &&
            (result.ticket.id !== ticket.id ||
              !Array.isArray(result.ticket.flags) ||
              typeof result.ticket.name !== "string" ||
              typeof result.ticket.kind !== "string" ||
              typeof result.ticket.status !== "string" ||
              typeof result.ticket.user_id !== "string" ||
              !Number.isInteger(result.ticket.number) ||
              result.ticket.number < 1)) ||
          (!ticket.number && (!result.ticket || result.ticket.id !== ticket.id))
        )
          throw new Error(
            "The ticket response is incomplete. Retry loading messages.",
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
    refreshRead.current = () => {
      void load();
    };
    void load();
    return () => {
      alive = false;
      refreshRead.current = () => {};
    };
  }, [ticket.id, space, before, reload]);
  useEffect(() => {
    if (paused || before) return;
    const timer = setInterval(() => {
      if (!document.hidden) refreshRead.current();
    }, 30000);
    return () => clearInterval(timer);
  }, [paused, before]);
  if (denied)
    return (
      <section className="ticket-browser">
        <button onClick={onBack}>
          <ArrowLeft size={16} aria-hidden="true" /> Back to tickets
        </button>
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
      <button onClick={onBack}>
        <ArrowLeft size={16} aria-hidden="true" /> Back to tickets
      </button>
      <CwlPageHeader
        className="ticket-heading"
        title={
          <h1 ref={heading} tabIndex={-1}>
            {identityReady
              ? `#${currentTicket.number} · ${currentTicket.name}`
              : "Loading ticket…"}
          </h1>
        }
        description={
          identityReady
            ? `${currentTicket.kind.toUpperCase()} · ${statusName(currentTicket.status)} · Read only`
            : "Checking access…"
        }
      >
        <RefreshControl
          updatedAt={data ? data.checked_at * 1000 : null}
          busy={busy}
          onRefresh={() => setReload((n) => n + 1)}
          intervalSeconds={!before ? 30 : undefined}
          paused={paused}
          onPauseChange={(next) => {
            setPaused(next);
            if (!next) refreshRead.current();
          }}
          showRefresh={!error}
        />
      </CwlPageHeader>
      {identityReady && (
        <DiscordIdentity
          userId={currentTicket.user_id}
          displayName={currentTicket.name}
          resolvedMember={null}
        />
      )}
      <p>Reply and handle this application in Discord.</p>
      {identityReady && <small>Opened {when(currentTicket.created_at)}</small>}
      {currentTicket.flags.length > 0 && (
        <div className="ticket-flag-details" aria-label="Applicant flags">
          <h2>Applicant flags</h2>
          {currentTicket.flags.map((item, index) => (
            <p key={`${item.kind}-${index}`}>
              <strong>{item.label}</strong>
              {item.reason ? ` · ${item.reason}` : ""}
            </p>
          ))}
        </div>
      )}
      <SectionTabs
        id="ticket-conversation"
        className="ticket-conversation-tabs section-tabs--flow"
        label="Ticket conversation"
        items={[
          { id: "applicant", label: <>Applicant</> },
          { id: "staff", label: <>Staff</> },
        ]}
        value={space}
        onChange={(next) => {
          switch (next) {
            case "applicant":
              {
                setSpace("applicant");
                setBefore("");
              }
              break;
            case "staff":
              {
                setSpace("staff");
                setBefore("");
              }
              break;
          }
        }}
        revealSelection
      />
      <SectionTabPanel id="ticket-conversation" value={space}>
        <div className="ticket-reader-tools">
          {data && (
            <a
              className="button"
              href={data.discord_url}
              target="_blank"
              rel="noreferrer"
            >
              Open conversation in Discord{" "}
              <ArrowUpRight size={16} aria-hidden="true" />
            </a>
          )}
        </div>
        {before && (
          <p className="small">
            Reading older messages. Automatic refresh is paused.
          </p>
        )}
        <LoadError
          message={error}
          note={data ? "Showing the last update." : undefined}
          onRetry={() => setReload((n) => n + 1)}
          busy={busy}
          retryContext="ticket messages"
        />
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
                    {...searchInputProps}
                    type="search"
                    placeholder="Name or words in this page"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </label>{" "}
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
                        System message or content unavailable. Open in Discord
                        to check.
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
                    : "No messages returned. If Discord shows messages, ask an owner to check the WU Wizard Read Message History and Message Content access."}
                </p>
              )}
            </div>
            <p className="small">
              Attachments open from Discord. Deleted messages and threads may no
              longer be available.
            </p>
          </>
        )}
      </SectionTabPanel>
    </section>
  );
}
