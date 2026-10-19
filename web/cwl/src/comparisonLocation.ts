export type ComparisonLocation = {
  current_clan_tag: string | null
  current_clan_name: string | null
  current_clan_checked_at?: string
  location_updating?: boolean
  arrival_status: string
}
export function comparisonLocation(location: ComparisonLocation | undefined, clanTag: string, now: number) {
  const checked = Date.parse(location?.current_clan_checked_at || '')
  if (!location || location.location_updating || location.arrival_status === 'unknown' || !Number.isFinite(checked) || now - checked > 120000) {
    return {state: 'unknown', label: location?.location_updating ? 'Updating…' : 'Not checked', detail: 'Refresh clan locations to check.'}
  }
  const arrived = location.current_clan_tag === clanTag
  return {state: arrived ? 'arrived' : 'missing', label: arrived ? 'In this clan' : 'Not in this clan', detail: `Current clan: ${location.current_clan_name || location.current_clan_tag || 'No clan'} · Checked ${new Date(checked).toLocaleTimeString()}`}
}
