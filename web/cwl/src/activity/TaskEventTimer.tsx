import { countdown, gameCalendar, localTime } from './calendar'

/** The same standard calendar as Events; independent of activity API availability. */
export default function TaskEventTimer({ kind, now }: { kind: 'raid' | 'games' | 'cwl'; now: number }) {
  const event = gameCalendar(now).find(item => item.id === kind)!
  const live = now >= event.start && now < event.end
  const cwl = kind === 'cwl'
  const target = live ? event.end : event.start
  return <aside className="todo-event-timer" aria-label={`${event.title} schedule`}>
    <div>
      <span className="todo-event-label">{event.title} · {cwl ? (live ? 'Clan signup open' : 'Next clan signup') : live ? 'Live window' : 'Next event'}</span>
      <strong>{cwl ? (live ? 'Signup closes' : 'Signup opens') : live ? 'Ends' : 'Starts'} in {countdown(target, now)}</strong>
      <time dateTime={new Date(target).toISOString()}>{localTime(target)}</time>
    </div>
    <p>{cwl ? 'This is the time when clans sign up in the game. Each clan has its own battle times. Your attack tasks and battle timers appear below after the game reports a war.' : live
      ? 'Progress appears below as activity is reported. If it has not appeared yet, check again after playing.'
      : 'New event progress will appear here after the event starts and activity is reported.'}
      <small>This is the usual game schedule, the same as on Events. If the in-game timer is different, use the in-game timer.</small>
    </p>
  </aside>
}
