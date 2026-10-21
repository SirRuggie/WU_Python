import type { Timing } from '../reminderCampaign'

/** Calendar fields in the campaign timezone; do not reinterpret as browser-local. */
export function timingDate(value: Timing | string, cycle: string | null, timezone: string): string {
  const rule = typeof value === 'string' ? {at:value} : value
  if ('at' in rule) {
    if (!rule.at) return ''
    if (!/(Z|[+-]\d\d:\d\d)$/.test(rule.at)) return rule.at.slice(0,16)
    try {
      const parts = new Intl.DateTimeFormat('en-CA', {timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(rule.at))
      const get = (type:string) => parts.find(part=>part.type===type)?.value
      return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`
    } catch { return '' }
  }
  if (!cycle || (rule.mode && rule.mode !== 'monthly')) return ''
  const [year, month] = cycle.split('-').map(Number)
  const first = new Date(Date.UTC(year,month-1+(rule.month_offset || 0),1))
  const days = new Date(Date.UTC(first.getUTCFullYear(),first.getUTCMonth()+1,0)).getUTCDate()
  if (rule.missing_day === 'skip' && Number(rule.day) > days) return ''
  const day = rule.month_end_offset_days !== undefined ? days-rule.month_end_offset_days : Math.min(rule.day ?? (rule.mode ? 1 : days-2),days)
  return `${first.getUTCFullYear()}-${String(first.getUTCMonth()+1).padStart(2,'0')}-${String(day).padStart(2,'0')}T${String(rule.hour ?? 17).padStart(2,'0')}:${String(rule.minute ?? 0).padStart(2,'0')}`
}
