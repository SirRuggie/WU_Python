import TownHallIcon from './TownHallIcon'
import { todoTime, type TodoKind, type TodoRow } from './todo'

export default function TodoTaskCard({ row, kind, now }: { row: TodoRow; kind: TodoKind; now: number }) {
  const privateRow = kind === 'private'
  const games = kind === 'games'
  const preparation = row.state === 'preparation'
  const gamesAwaitingRefresh = games && row.state === 'upcoming' && row.starts_at !== null && now >= row.starts_at * 1000
  const measurable = row.used !== null && row.total !== null && row.total > 0 && !privateRow && !games
  const timestamp = preparation ? row.starts_at : row.ends_at
  const status = privateRow ? (row.detail === 'private' ? 'Private war log' : 'Unable to check')
    : games ? (row.state === 'upcoming' ? (gamesAwaitingRefresh ? 'Waiting for update' : 'Not started') : row.used === null ? 'Not available' : `${row.used.toLocaleString()} points earned`)
    : preparation ? 'Preparation day' : `${row.remaining ?? '—'} attack${row.remaining === 1 ? '' : 's'} left`
  return <article className="todo-task">
    <div className="todo-task-name">
      <TownHallIcon level={row.town_hall}/>
      <div><strong>{row.name}</strong><small>{row.tag}</small></div>
      <a href={`https://link.clashofclans.com/en?action=OpenPlayerProfile&tag=${encodeURIComponent(row.tag)}`}
        target="_blank" rel="noopener noreferrer" aria-label={`Open ${row.name} in Clash of Clans`}>↗</a>
    </div>
    <div className="todo-task-progress">
      <span className={`todo-state ${preparation || row.state === 'upcoming' ? 'prep' : privateRow || (games && row.used === null) ? 'blocked' : ''}`}>{status}</span>
      {measurable && <>
        <progress max={row.total!} value={Math.min(row.used!, row.total!)} aria-label={`${row.name}: ${row.used} of ${row.total} attacks used`}/>
        <small>{row.used} of {row.total} attacks used</small>
      </>}
    </div>
    <div className="todo-task-time">
      {privateRow ? <p>{row.detail === 'private' ? 'Check attacks in-game. A clan leader can make the war log public.'
        : row.detail && row.detail !== 'error' ? row.detail : 'Could not check this war. Try again or check in-game.'}</p>
        : games ? <p>{gamesAwaitingRefresh ? 'Refresh to check this event’s points.' : row.detail || 'This event · Tracked scores'}</p>
        : <>
          <small>{preparation ? 'Battle starts in' : 'Ends in'}</small>
          <strong>{todoTime(timestamp, now)}</strong>
          {timestamp && <time dateTime={new Date(timestamp * 1000).toISOString()}>{new Date(timestamp * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'})}</time>}
        </>}
    </div>
  </article>
}
