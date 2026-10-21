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
    <p>{cwl ? 'This is the in-game clan signup window. Each clan’s battle schedule is different. Your attack tasks and battle timers appear below when wars are reported.' : live
      ? 'Progress appears below as activity is reported. If it has not appeared yet, check again after playing.'
      : 'New event progress will appear here after the event starts and activity is reported.'}
      <small>Standard game schedule, same as Events. The in-game timer takes precedence.</small>
    </p>
  </aside>
}
