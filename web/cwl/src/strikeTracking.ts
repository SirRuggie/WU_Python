export type TrackingStatus = 'healthy' | 'behind' | 'private' | 'error'
export type CurrentWarState =
  'notInWar' | 'preparation' | 'inWar' | 'warEnded' | 'private' | 'unknown'
export type DisplayTrackingStatus = TrackingStatus | 'unverified'

export type ClanTracking = {
  clan_tag: string
  clan_name: string
  status: TrackingStatus
  current_war_state?: CurrentWarState | null
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

export type TrackingResponse = {
  clans: ClanTracking[]
  summary?: {
    healthy: number
    behind: number
    private: number
    error: number
    total: number
  }
}

export function displayTrackingStatus(
  clan: ClanTracking,
): DisplayTrackingStatus {
  // A missing record and unconfirmed war state cannot establish a healthy scan.
  if (
    clan.status === 'healthy' &&
    !clan.latest_recorded_war_at &&
    clan.current_war_state !== 'notInWar'
  ) {
    return 'unverified'
  }
  return clan.status
}

export function trackingSummary(clans: ClanTracking[]): {
  label: string
  tone: 'healthy' | 'warning' | 'unknown'
} {
  if (!clans.length) return { label: 'No clans tracked', tone: 'unknown' }
  const counts = { healthy: 0, behind: 0, private: 0, error: 0, unverified: 0 }
  for (const clan of clans) counts[displayTrackingStatus(clan)] += 1
  if (counts.healthy === clans.length) {
    return {
      label: `${clans.length} ${clans.length === 1 ? 'clan' : 'clans'} on track`,
      tone: 'healthy',
    }
  }
  const parts = [
    counts.healthy && `${counts.healthy} on track`,
    counts.behind && `${counts.behind} behind`,
    counts.private && `${counts.private} private`,
    counts.error && `${counts.error} error`,
    counts.unverified && `${counts.unverified} unverified`,
  ].filter(Boolean)
  return { label: parts.join(' · '), tone: 'warning' }
}

export function trackingStatusLabel(status: DisplayTrackingStatus): string {
  switch (status) {
    case 'healthy':
      return 'On track'
    case 'behind':
      return 'Behind'
    case 'private':
      return 'War log private'
    case 'error':
      return 'Error'
    case 'unverified':
      return 'Unverified'
  }
}

export function currentWarStateLabel(state?: CurrentWarState | null): string {
  switch (state) {
    case 'notInWar':
      return 'Not in war'
    case 'preparation':
      return 'Preparation'
    case 'inWar':
      return 'In war'
    case 'warEnded':
      return 'War ended'
    case 'private':
      return 'War log private'
    default:
      return 'Unknown'
  }
}

export function trackingIssues(clan: ClanTracking): string {
  const notes = []
  if (clan.deferred_accounts)
    notes.push(
      `${clan.deferred_accounts} ${clan.deferred_accounts === 1 ? 'account needs' : 'accounts need'} review`,
    )
  if (clan.skipped_wars)
    notes.push(
      `${clan.skipped_wars} skipped ${clan.skipped_wars === 1 ? 'war' : 'wars'}`,
    )
  return notes.join(' · ')
}
