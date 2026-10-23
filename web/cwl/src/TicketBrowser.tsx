import TicketConversation from './TicketConversation'
import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import './TicketBrowser.css'
export type Ticket = {
  id: string
  number: number
  name: string
  user_id: string
  kind: string
  status: string
  created_at: string | null
  flags: { kind: string; label: string; reason: string }[]
}
const statusName = (value: string) =>
  ({ open: 'Open', approved: 'Approved', denied: 'Denied', closed: 'Closed' })[
    value
  ] || value
const when = (value: string | null) =>
  value ? new Date(value).toLocaleString() : 'Date unavailable'
export default function TicketBrowser() {
  const [status, setStatus] = useState('open'),
    [kind, setKind] = useState('all'),
    [flag, setFlag] = useState('all'),
    [search, setSearch] = useState(''),
    [query, setQuery] = useState(''),
    [from, setFrom] = useState(''),
    [to, setTo] = useState(''),
    [page, setPage] = useState(1),
    [tickets, setTickets] = useState<Ticket[]>([]),
    [more, setMore] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [reload, setReload] = useState(0),
    [selected, setSelected] = useState<Ticket | null>(null)
  const returnTicket = useRef<string | null>(null)
  const returnReady = useRef(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const ticketButtons = useRef(new Map<string, HTMLButtonElement>())
  useEffect(() => {
    if (selected || busy || !returnReady.current || !returnTicket.current)
      return
    ;(
      ticketButtons.current.get(returnTicket.current) || heading.current
    )?.focus()
    returnTicket.current = null
    returnReady.current = false
  }, [selected, busy, tickets, error])
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search)
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [search])
  useEffect(() => {
    if (selected) return
    let alive = true
    setBusy(true)
    setError('')
    setTickets([])
    const params = new URLSearchParams({
      status,
      kind,
      flag,
      q: query,
      from,
      to,
      page: String(page),
    })
    api<{ tickets: Ticket[]; has_more: boolean }>(`/manage/tickets?${params}`)
      .then((result) => {
        if (alive) {
          setTickets(result.tickets)
          setMore(result.has_more)
        }
      })
      .catch((e) => {
        if (alive) {
          setError(e.message)
          setMore(false)
        }
      })
      .finally(() => {
        if (alive) {
          returnReady.current = true
          setBusy(false)
        }
      })
    return () => {
      alive = false
    }
  }, [selected, status, kind, flag, query, from, to, page, reload])
  const extraFilters = Number(flag !== 'all') + Number(!!from) + Number(!!to)
  const clearFilters = () => {
    setSearch('')
    setQuery('')
    setStatus('all')
    setKind('all')
    setFlag('all')
    setFrom('')
    setTo('')
    setPage(1)
  }
  if (selected)
    return (
      <TicketConversation
        ticket={selected}
        onBack={() => {
          returnReady.current = false
          setBusy(true)
          setSelected(null)
        }}
      />
    )
  return (
    <section className="ticket-browser">
      <div className="page-head">
        <div>
          <p className="eyebrow">Staff · Read only</p>
          <h1 ref={heading} tabIndex={-1}>
            Tickets
          </h1>
          <p>
            Review applications and conversations. Reply or make decisions in
            Discord.
          </p>
        </div>
        <button disabled={busy} onClick={() => setReload((n) => n + 1)}>
          Refresh
        </button>
      </div>
      <div className="ticket-filters">
        <label>
          Find a ticket
          <input
            type="search"
            placeholder="Member, ticket # or player tag"
            maxLength={80}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label>
          Status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value)
              setPage(1)
            }}
          >
            <option value="closed">Closed tickets</option>
            <option value="open">Open tickets</option>
            <option value="all">All tickets</option>
            <option value="approved">Approved</option>
            <option value="denied">Denied</option>
          </select>
        </label>
        <label>
          Type
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value)
              setPage(1)
            }}
          >
            <option value="all">Main and FWA</option>
            <option value="main">Main</option>
            <option value="fwa">FWA</option>
          </select>
        </label>
      </div>
      <details className="ticket-date-filter">
        <summary>
          More filters{extraFilters ? ` · ${extraFilters} active` : ''}
        </summary>
        <div>
          <label>
            Applicant flag
            <select
              value={flag}
              onChange={(e) => {
                setFlag(e.target.value)
                setPage(1)
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
                setFrom(e.target.value)
                setPage(1)
              }}
            />
          </label>
          <label>
            To
            <input
              type="date"
              value={to}
              onChange={(e) => {
                setTo(e.target.value)
                setPage(1)
              }}
            />
          </label>
          <small>Dates use UTC.</small>
        </div>
      </details>
      <div className="ticket-list-summary">
        <span>
          {busy
            ? 'Loading…'
            : error
              ? 'Tickets unavailable'
              : `${tickets.length} tickets on this page`}
        </span>
        {(search ||
          status !== 'open' ||
          kind !== 'all' ||
          extraFilters > 0) && (
          <button onClick={clearFilters}>Clear filters</button>
        )}
      </div>
      {error && (
        <p className="notice error" role="alert">
          {error}
          <button onClick={() => setReload((n) => n + 1)}>
            Retry loading tickets
          </button>
        </p>
      )}
      {busy ? (
        <p role="status">Loading tickets…</p>
      ) : !error && !tickets.length ? (
        <div className="card empty">
          <h2>No tickets found</h2>
          <p>Try another name, status or date.</p>
          <button onClick={clearFilters}>Clear filters</button>
        </div>
      ) : (
        <div className="ticket-list">
          {tickets.map((t) => (
            <article className="ticket-row" key={t.id}>
              <div>
                <strong>
                  #{t.number} · {t.name}
                </strong>
                <small>
                  {t.kind.toUpperCase()} · {statusName(t.status)} · Opened{' '}
                  {when(t.created_at)}
                </small>
                {t.flags.length > 0 && (
                  <ul className="ticket-flags" aria-label="Applicant flags">
                    {t.flags.map((item, index) => (
                      <li key={`${item.kind}-${index}`}>{item.label}</li>
                    ))}
                  </ul>
                )}
              </div>
              <button
                ref={(node) => {
                  if (node) ticketButtons.current.set(t.id, node)
                  else ticketButtons.current.delete(t.id)
                }}
                aria-label={`Read ticket ${t.number} · ${t.name}`}
                onClick={() => {
                  returnTicket.current = t.id
                  setSelected(t)
                }}
              >
                Read →
              </button>
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
  )
}
