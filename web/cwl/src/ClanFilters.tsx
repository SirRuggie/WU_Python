import { useRef } from 'react'
import './ClanFilters.css'

export const leagueValue = (value?: string | null) => value || 'League unavailable'
export const matchesLeague = (value: string | null | undefined, selected: string[]) => !selected.length || selected.includes(leagueValue(value))
export const matchesTownHall = (value: number | null, selected: string[]) => !selected.length || selected.includes(value == null ? 'Unknown TH' : `TH ${value}`)

type FilterProps = {
  label: string
  options: string[]
  selected: string[]
  onChange: (values: string[]) => void
  disabled?: boolean
}

export function FilterPicker({ label, options, selected, onChange, disabled = false }: FilterProps) {
  const summary = useRef<HTMLElement>(null)
  return <details className="filter-picker" onKeyDown={event => {
    if (event.key === 'Escape' && event.currentTarget.open) {
      event.preventDefault()
      event.stopPropagation()
      event.currentTarget.open = false
      summary.current?.focus()
    }
  }}>
    <summary ref={summary} aria-disabled={disabled || undefined} onClick={event => {
      if (disabled) event.preventDefault()
    }}>{label}<span>{selected.length ? `${selected.length} selected` : 'All'} ▾</span></summary>
    <div className="filter-picker-options" role="group" aria-label={`${label} options`}>
      <button type="button" disabled={disabled || !selected.length} onClick={() => onChange([])}>Show all</button>
      {options.map(value => <label key={value}>
        <input type="checkbox" disabled={disabled} checked={selected.includes(value)} onChange={event =>
          onChange(event.target.checked ? [...selected, value] : selected.filter(item => item !== value))
        } />{value}
      </label>)}
    </div>
  </details>
}
