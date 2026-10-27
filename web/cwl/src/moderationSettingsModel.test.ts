import { beforeEach, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => vi.fn())
vi.mock('./api', async original => ({
  ...(await original<typeof import('./api')>()),
  api: transport,
}))

import { ApiError } from './api'
import {
  hasInvalidDestination,
  moderationSettingsError,
  saveModerationSettings,
  type EventSettings,
  type SettingsResponse,
} from './moderationSettingsModel'

const events: EventSettings = {
  join: { enabled: true, channel_id: 'text-1', forum_tag_id: null },
  leave: { enabled: false, channel_id: null, forum_tag_id: null },
  kick: { enabled: false, channel_id: null, forum_tag_id: null },
  ban: { enabled: false, channel_id: null, forum_tag_id: null },
}
const settings: SettingsResponse = {
  revision: 7,
  events,
  channels_available: true,
  channels: [
    {
      id: 'text-1', name: 'mod-log', type: 'text', can_post: true,
      requires_tag: false, can_manage_threads: false, available_tags: [],
    },
  ],
}

beforeEach(() => transport.mockReset())

it('saves only the draft with the loaded revision for compare-and-swap', async () => {
  transport.mockResolvedValue({ revision: 8, events })
  await saveModerationSettings(settings, events)
  expect(transport).toHaveBeenCalledWith('/manage/member-events/settings', 'PUT', {
    revision: 7,
    events,
  })
})

it('keeps edits available after a stale revision response', async () => {
  const draft = { ...events, leave: { enabled: true, channel_id: 'text-1', forum_tag_id: null } }
  expect(draft.leave.enabled).toBe(true)
  expect(moderationSettingsError(new ApiError('Revision changed', 409), 'save')).toMatchObject({
    stale: true,
    denied: false,
  })
})

it('validates post permissions and only requires forum tags when configured', () => {
  expect(hasInvalidDestination(events, settings.channels)).toBe(false)
  const forum = {
    id: 'forum-1', name: 'moderation', type: 'forum' as const, can_post: true,
    requires_tag: false, can_manage_threads: false,
    available_tags: [{ id: 'tag-1', name: 'Moderated', moderated: true }],
  }
  const forumDraft = {
    ...events,
    join: { enabled: true, channel_id: forum.id, forum_tag_id: null },
  }
  expect(hasInvalidDestination(forumDraft, [forum])).toBe(false)
  expect(hasInvalidDestination({
    ...forumDraft,
    join: { ...forumDraft.join, forum_tag_id: 'tag-1' },
  }, [forum])).toBe(true)
  expect(hasInvalidDestination(forumDraft, [{ ...forum, can_post: false }])).toBe(true)
  expect(hasInvalidDestination(forumDraft, [forum], false)).toBe(true)
})


it('accepts a verified existing forum post without requiring a parent forum tag', () => {
  const post = {
    id: 'post-1', name: 'Member history', type: 'forum_post' as const,
    can_post: true, requires_tag: false, can_manage_threads: false, available_tags: [],
  }
  const draft = { ...events, join: { enabled: true, channel_id: post.id, forum_tag_id: null } }
  expect(hasInvalidDestination(draft, [post])).toBe(false)
  expect(hasInvalidDestination(draft, [])).toBe(true)
  expect(hasInvalidDestination(draft, [{ ...post, can_post: false }])).toBe(true)
})
