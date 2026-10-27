import { api, ApiError } from './api'

export type ModerationKind = 'join' | 'leave' | 'kick' | 'ban'
export type EventConfig = { enabled: boolean; channel_id: string | null; forum_tag_id: string | null }
export type EventSettings = Record<ModerationKind, EventConfig>
export type Destination = {
  id: string
  name: string
  type: 'text' | 'forum'
  available_tags: { id: string; name: string; moderated: boolean }[]
  can_post: boolean
  requires_tag: boolean
  can_manage_threads: boolean
}
export type SettingsResponse = { revision: number; events: EventSettings; channels?: Destination[] | null; channels_available?: boolean; warning?: string | null }
export const eventTypes: { key: ModerationKind; label: string; explanation: string }[] = [
  { key: 'join', label: 'Member joins', explanation: 'Post when a member joins the server.' },
  { key: 'leave', label: 'Member leaves', explanation: 'Post when a member leaves the server.' },
  { key: 'kick', label: 'Member kicks', explanation: 'Post verified member kick events.' },
  { key: 'ban', label: 'Member bans', explanation: 'Post verified member ban events.' },
]

export function cloneEvents(events: EventSettings): EventSettings {
  return Object.fromEntries(eventTypes.map(({ key }) => [key, { ...events[key] }])) as EventSettings
}

export function changedEvents(saved: EventSettings, draft: EventSettings) {
  return JSON.stringify(saved) !== JSON.stringify(draft)
}

export function hasInvalidDestination(draft: EventSettings, channels: Destination[] | null | undefined, channelsAvailable = true) {
  return eventTypes.some(({ key }) => {
    const event = draft[key]
    if (!event.enabled) return false
    if (!channelsAvailable || !channels) return true
    const channel = channels.find(item => item.id === event.channel_id)
    if (!channel || !channel.can_post) return true
    if (channel.type !== 'forum') return false
    if (channel.requires_tag && !event.forum_tag_id) return true
    if (!event.forum_tag_id) return false
    const tag = channel.available_tags.find(item => item.id === event.forum_tag_id)
    return !tag || (tag.moderated && !channel.can_manage_threads)
  })
}

export function saveModerationSettings(saved: SettingsResponse, draft: EventSettings) {
  return api<SettingsResponse>('/manage/member-events/settings', 'PUT', {
    revision: saved.revision,
    events: cloneEvents(draft),
  })
}

export function moderationSettingsError(cause: unknown, operation: 'read' | 'save') {
  if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
    return { denied: true, stale: false, message: 'Your staff access has changed. Sign in again or ask an administrator to restore access.' }
  }
  if (operation === 'save' && cause instanceof ApiError && cause.status === 409) {
    return { denied: false, stale: true, message: 'These settings changed since you loaded them. Your edits are preserved; reload the latest version before saving again.' }
  }
  return {
    denied: false,
    stale: false,
    message: cause instanceof Error ? cause.message : operation === 'read'
      ? 'Could not load moderation settings.'
      : 'Could not save moderation settings. Your edits are preserved.',
  }
}
