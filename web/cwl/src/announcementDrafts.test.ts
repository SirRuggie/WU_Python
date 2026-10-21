import { expect, it } from 'vitest'
import { reconcileAnnouncementSave } from './announcementDrafts'
const previous = {main:{channel_id:'main',body:'Main saved',roster_url:'https://example.com'},lazy:{channel_id:'lazy',body:'Lazy saved',roster_url:'https://example.com'}}
it('acknowledges Lazy while preserving Main text, channel, and link drafts', () => {
  const drafts = {main:{channel_id:'other',body:'Main unsaved',roster_url:'https://example.com/new'},lazy:{...previous.lazy,body:'Lazy updated'}}
  const result = reconcileAnnouncementSave('lazy', drafts, previous, {...previous,lazy:drafts.lazy})
  expect(result.drafts.main).toEqual(drafts.main)
  expect(result.drafts.lazy).toEqual(drafts.lazy)
  expect(result.conflict).toBe(false)
})
it('does not silently adopt a newer generation over concurrent edits to the other pool', () => {
  const drafts = {...previous,main:{...previous.main,body:'Local edit'}}
  const result = reconcileAnnouncementSave('lazy',drafts,previous,{...previous,main:{...previous.main,body:'External edit'}})
  expect(result.conflict).toBe(true)
  expect(result.drafts.main.body).toBe('Local edit')
})
it('applies the same isolation when Main is saved', () => {
  const drafts = {...previous,lazy:{...previous.lazy,body:'Unsaved lazy'}}
  expect(reconcileAnnouncementSave('main',drafts,previous,previous).drafts.lazy.body).toBe('Unsaved lazy')
})
