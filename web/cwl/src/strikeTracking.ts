export type ClanTracking = {
  clan_tag: string
  clan_name: string
  status: 'healthy' | 'delayed' | 'needs_review'
  last_checked_at?: string | null
  last_success_at?: string | null
  latest_recorded_war_at?: string | null
  regular_wars?: number
  cwl_wars?: number
  deferred_accounts?: number
  skipped_wars?: number
  error?: string | null
  retry_pending?: boolean
  retry_requested_at?: string | null
}

export function trackingSummary(clans: ClanTracking[]): { label: string; tone: 'healthy' | 'warning' | 'unknown' } {
  if (!clans.length) return { label: 'No clans tracked', tone: 'unknown' }
  const review = clans.filter(item => item.status === 'needs_review').length
  const delayed = clans.filter(item => item.status === 'delayed').length
  if (review) return { label: `${review} ${review === 1 ? 'clan needs' : 'clans need'} review${delayed ? ` · ${delayed} delayed` : ''}`, tone: 'warning' }
  if (delayed) return { label: `${delayed} ${delayed === 1 ? 'clan' : 'clans'} delayed`, tone: 'warning' }
  return { label: `${clans.length} ${clans.length === 1 ? 'clan' : 'clans'} on track`, tone: 'healthy' }
}

export function trackingStatusLabel(status: ClanTracking['status']): string {
  return status === 'healthy' ? 'On track' : status === 'delayed' ? 'Delayed' : 'Needs review'
}

export function trackingIssues(clan: ClanTracking): string {
  const notes = []
  if (clan.deferred_accounts) notes.push(`${clan.deferred_accounts} ${clan.deferred_accounts === 1 ? 'account needs' : 'accounts need'} review`)
  if (clan.skipped_wars) notes.push(`${clan.skipped_wars} skipped ${clan.skipped_wars === 1 ? 'war' : 'wars'}`)
  return notes.join(' · ')
}
