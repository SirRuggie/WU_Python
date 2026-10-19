import type { AnnouncementChannel } from './announcements'
export function filterChannels(channels: AnnouncementChannel[], query: string): AnnouncementChannel[] {
  const term = query.trim().replace(/^#/, '').toLocaleLowerCase()
  return term ? channels.filter(channel => channel.name.toLocaleLowerCase().includes(term) || channel.id.includes(term)) : channels
}
