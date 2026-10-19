import './ClanFilters.css'
export const leagueValue = (value?: string | null) => value || 'League unavailable'
export const matchesLeague = (value: string | null | undefined, selected: string[]) => !selected.length || selected.includes(leagueValue(value))
export const matchesTownHall = (value: number | null, selected: string[]) => !selected.length || selected.includes(value == null ? 'Unknown TH' : `TH ${value}`)
export function FilterPicker({label, options, selected, onChange}: {label:string;options:string[];selected:string[];onChange:(values:string[])=>void}) {
  return <details className="filter-picker"><summary>{label}<span>{selected.length ? `${selected.length} selected` : 'All'} ▾</span></summary><div className="filter-picker-options"><button type="button" disabled={!selected.length} onClick={()=>onChange([])}>Show all</button>{options.map(value=><label key={value}><input type="checkbox" checked={selected.includes(value)} onChange={event=>onChange(event.target.checked?[...selected,value]:selected.filter(item=>item!==value))}/>{value}</label>)}</div></details>
}
