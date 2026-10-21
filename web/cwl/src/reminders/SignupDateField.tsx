import type { Timing } from '../reminderCampaign'
import { timingDate } from './signupTiming'

type Props = {
  label: string
  value: Timing | string
  cycle: string | null
  timezone: string
  deadline?: boolean
  onChange: (value: Timing) => void
}

export default function SignupDateField({label, value, cycle, timezone, deadline, onChange}: Props) {
  const date = timingDate(value, cycle, timezone)
  const rule = typeof value === 'string' ? {at: value} : value
  const manual = !deadline && (!rule.mode || rule.mode === 'manual')
  return <section className="signup-date-field">
    <h3>{label}</h3>
    {!deadline && <label className="check-label">
      <input type="checkbox" checked={!manual} onChange={event =>
        onChange(event.target.checked ? {mode: 'specific', at: date} : {mode: 'manual'})}/>
      Schedule the opening announcement
    </label>}
    {!manual && <label>{label} date and time
      <input type="datetime-local" value={date} onChange={event =>
        onChange({...(deadline ? {} : {mode: 'specific'}), at: event.target.value})}/>
    </label>}
    <p className="small">{manual
      ? 'The opening announcement is sent manually. Turn on scheduling to choose its date.'
      : rule.month_end_offset_days !== undefined
        ? `Currently repeats ${rule.month_end_offset_days} days before the end of each month. Choosing a date changes this to the same day each month.`
        : 'Repeats on this day each month. Times use the schedule timezone.'}</p>
  </section>
}
