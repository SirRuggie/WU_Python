import { countdown, localTime } from './activity/calendar'
import type { TodoView } from './todo'

/** Scores always describe the displayed month, including after its event ends. */
export default function ClanGamesSummary({ view, now }: { view: TodoView; now: number }) {
  if (!view.season || !view.event_start || !view.event_end) return null
  const start = view.event_start * 1000
  const end = view.event_end * 1000
  const upcoming = now < start
  const ended = now >= end
  const label = new Date(`${view.season}-01T12:00:00Z`).toLocaleDateString([], {
    month: 'long', year: 'numeric', timeZone: 'UTC',
  })
  return <aside className="todo-event-timer" aria-label="Clan Games schedule">
    <div>
      <span className="todo-event-label">Clan Games · {label}</span>
      <strong>{ended ? 'Event ended' : `${upcoming ? 'Starts' : 'Ends'} in ${countdown(upcoming ? start : end, now)}`}</strong>
      <time dateTime={new Date(upcoming ? start : end).toISOString()}>{localTime(upcoming ? start : end)}</time>
    </div>
    <p>{upcoming ? 'Points will appear here after the event starts.' : 'Points earned this event. Scores may take a few minutes to update.'}
      <small>Tracked scores{view.checked_at && <> · Last checked {localTime(Date.parse(view.checked_at))}</>}</small>
    </p>
  </aside>
}
