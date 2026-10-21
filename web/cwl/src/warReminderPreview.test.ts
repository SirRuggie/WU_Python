import {describe,it,expect} from 'vitest'
import {reminderPreviewText} from './warReminderPreview'
describe('reminder timestamp preview',()=>{
 it('shows readable deadlines while preserving player text',()=>{expect(reminderPreviewText('Ends <t:3600:R> · Shield Bearer — 0/2',0)).toBe('Ends in 1 hour · Shield Bearer — 0/2')})
 it('shows custom minute intervals and local time',()=>{expect(reminderPreviewText('<t:4500:R>',0)).toBe('in 75 minutes');expect(reminderPreviewText('<t:3600:t>',0)).not.toContain('<t:')})
})
