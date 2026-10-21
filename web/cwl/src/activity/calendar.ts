/** Recurring UTC schedule, reviewed 2026-10-21. See docs/activity-calendar.md.
 * These are standard windows, not proof that a clan has joined an event.
 */
import type { DashboardIconName } from '../DashboardIcon'
export type GameEvent = { id: string; title: string; description: string; icon: DashboardIconName; start: number; end: number; endLabel?: string }
const DAY = 86400000
const utc = (year: number, month: number, day: number, hour: number) => Date.UTC(year, month, day, hour)

export function gameCalendar(now: number): GameEvent[] {
  const date = new Date(now), year = date.getUTCFullYear(), month = date.getUTCMonth()
  const monthly = (startDay: number, endDay: number, hour: number) => {
    const offset = now >= utc(year, month, endDay, hour) ? 1 : 0
    return {start: utc(year, month + offset, startDay, hour), end: utc(year, month + offset, endDay, hour)}
  }
  let friday = utc(year, month, date.getUTCDate() - (date.getUTCDay() + 2) % 7, 7)
  if (now >= friday + 3 * DAY) friday += 7 * DAY
  const anchor = Date.UTC(2025, 10, 3, 5)
  const seasonStart = anchor + Math.floor((now - anchor) / (28 * DAY)) * 28 * DAY
  return [
    {id:'season', title:'Trophy season', icon:'trophy', description:'The 28-day league season. Separate from the monthly Gold Pass season.', start:seasonStart, end:seasonStart + 28 * DAY},
    {id:'games', title:'Clan Games', icon:'games', description:'Complete challenges together to unlock your clan’s reward tiers.', ...monthly(22, 28, 8)},
    {id:'raid', title:'Raid weekend', icon:'raid', description:'Clans raid enemy capitals from Friday to Monday for Capital Gold and Raid Medals.', start:friday, end:friday + 3 * DAY},
    {id:'cwl', title:'Clan War Leagues', icon:'war', description:'Two days to enter matchmaking. Battle dates then depend on your clan’s group; see Wars for actual round times.', ...monthly(1, 3, 8), endLabel:'Signup closes'},
  ]
}

export function countdown(target: number, now: number): string {
  const minutes = Math.max(0, Math.ceil((target - now) / 60000))
  if (minutes < 1) return 'now'
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'}`
  const hours = Math.floor(minutes / 60), remainder = minutes % 60
  if (hours < 48) return `${hours} hour${hours === 1 ? '' : 's'}${remainder ? ` ${remainder}m` : ''}`
  const days = Math.floor(hours / 24)
  return `${days} days${hours % 24 ? ` ${hours % 24}h` : ''}`
}
export function localTime(value: number, zone?: string): string {
  return new Intl.DateTimeFormat(undefined, {weekday:'short', month:'short', day:'numeric', hour:'numeric', minute:'2-digit', timeZoneName:'short', ...(zone ? {timeZone:zone} : {})}).format(value)
}
