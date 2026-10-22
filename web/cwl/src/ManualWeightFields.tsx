import { useId } from 'react'
import { manualWeightFields, type ManualWeightDraft } from './manualWeight'
import './ManualWeightFields.css'

type Props = {
  value: ManualWeightDraft
  onChange: (value: ManualWeightDraft) => void
  disabled?: boolean
}
export default function ManualWeightFields({ value, onChange, disabled }: Props) {
  const helpId = useId()
  const fields = manualWeightFields(value)
  return <div className="manual-weight-fields">
    <div className="manual-weight-inputs">
      <label>Loot<input type="text" inputMode="decimal" value={fields.loot}
        onChange={event => onChange({ unit: 'loot', text: event.target.value })}
        placeholder="e.g. 25,000" disabled={disabled} aria-describedby={helpId} /></label>
      <label>Full weight<input type="text" inputMode="numeric" value={fields.full}
        onChange={event => onChange({ unit: 'full', text: event.target.value })}
        placeholder="e.g. 125,000" disabled={disabled} aria-describedby={helpId} /></label>
    </div>
    <small id={helpId}>Loot × 5 = full weight. Enter either amount, without “k”.</small>
  </div>
}
