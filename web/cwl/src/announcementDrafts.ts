import type { Pool } from './api'
export type AnnouncementDraft = { channel_id: string; body: string; roster_url: string }
export type AnnouncementDrafts = Record<Pool, AnnouncementDraft>
const equal = (left: AnnouncementDraft, right: AnnouncementDraft) =>
  left.channel_id === right.channel_id && left.body === right.body && left.roster_url === right.roster_url

/** A pool save acknowledges only that pool. Other local work remains untouched. */
export function reconcileAnnouncementSave(pool: Pool, drafts: AnnouncementDrafts, previous: AnnouncementDrafts | null, saved: AnnouncementDrafts) {
  const other = pool === 'main' ? 'lazy' : 'main'
  const conflict = !!previous && !equal(previous[other], saved[other]) && !equal(previous[other], drafts[other])
  return { drafts: { ...drafts, [pool]: saved[pool] }, conflict }
}
