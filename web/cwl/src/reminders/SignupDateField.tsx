import type { ReactNode } from 'react'
import type { Timing } from '../reminderCampaign'
import { timingDate } from './signupTiming'

type Props = {
  label: string; value: Timing | string; cycle: string | null; timezone: string;
  deadline?: boolean; onChange: (value: Timing) => void; children: ReactNode;
}
export default function SignupDateField({label,value,cycle,timezone,deadline,onChange,children}: Props) {
  const date = timingDate(value,cycle,timezone)
  const manual = !deadline && typeof value !== 'string' && (!value.mode || value.mode === 'manual')
  return <section className="signup-date-field">
    <h3>{label}</h3>
    {manual && <p>Manual send only. Choose a date below to schedule the opening announcement.</p>}
    <label>{label} date and time
      <input type="datetime-local" value={date} onChange={event=>onChange({...(deadline ? {} : {mode:'specific'}),at:event.target.value})}/>
    </label>
    {!date && !manual && <p className="small">This uses a custom rule. Open advanced timing to inspect it, or choose a date to replace it.</p>}
    <details><summary>Advanced timing</summary>
      <p className="small">Existing recurring rules are preserved until you change them. Choosing a date replaces this rule.</p>
      {children}
    </details>
  </section>
}
