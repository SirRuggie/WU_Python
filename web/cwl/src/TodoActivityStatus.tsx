import type { TodoView } from './todo'

/** One notice per activity; diagnostic wording stays available on demand. */
export default function TodoActivityStatus({ view, hasRows, unreadable, onAffected }: {
  view: TodoView; hasRows: boolean; unreadable: number; onAffected: () => void
}) {
  if (view.loading) return null
  const failed = !view.ok || !!view.incomplete
  const details = [...new Set([view.incomplete, view.unavailable, view.note, ...view.notes]
    .flatMap(value => (value || '').split(';'))
    .map(value => value.trim()).filter(Boolean))]
  if (!failed && !unreadable) {
    return details.length ? <div className="todo-notes">{details.map(note => <p key={note}>{note}</p>)}</div> : null
  }
  return <div className="todo-warning" role="status">
    <strong>{failed ? hasRows ? 'Some tasks are missing' : 'Couldn’t load this activity' : 'Some war logs could not be checked'}</strong>
    <p>{failed
      ? hasRows ? 'Showing the results we could check. Check in-game for the rest.' : 'Clash data is unavailable. Check in-game for now, or try Check now again later.'
      : 'These accounts need checking in-game.'}</p>
    <details>
      <summary>Check details</summary>
      {details.map(note => <p key={note}>{note}</p>)}
      {unreadable > 0 && <button onClick={onAffected}>View affected accounts →</button>}
    </details>
  </div>
}
