import { describe, expect, it } from 'vitest'
import { campaignPatch, nextReminderOccurrence, type Campaign } from './reminderCampaign'
const variant = () => ({title:'Signup',body:'Original',media_url:'',destination_channel_id:'1072714594625257502',role_ids:['1080521665584308286'],enabled:true,buttons:[{label:'Sign up',url:'https://forms.gle/original'}]})
const campaign = (): Campaign => ({timezone:'America/New_York',paused:false,signup_deadline:{day:28,hour:17},reminder_sequence:{enabled:false},messages:{signup:{enabled:true,label:'Signup',schedule:{mode:'monthly',day:20},variants:{main:variant(),lazy:variant()}},roster:{enabled:true,label:'Roster',schedule:{mode:'manual'},variants:{main:variant(),lazy:variant()}}}})
describe('Shared reminder edits', () => {
 it('only sends changed editable fields, preserving large Discord IDs as strings', () => {
  const before = campaign(), after = campaign()
  after.messages.signup.variants.main.body = 'Updated'
  after.messages.signup.variants.main.destination_channel_id = '947166650321494067'
  expect(campaignPatch(before,after)).toEqual({messages:{signup:{variants:{main:{body:'Updated',destination_channel_id:'947166650321494067'}}}}})
 })
 it('never submits button changes, roster edits or pause through message saving', () => {
  const before = campaign(), after = campaign()
  after.messages.signup.variants.main.buttons[0].url = 'https://cwl.ruggie.zone/'
  after.messages.roster.variants.main.body = 'Unrelated'
  after.paused = true
  expect(campaignPatch(before,after)).toEqual({})
 })
 it('retains exact unchanged schedule rules and sends only edited timing', () => {
  const before = campaign(), after = campaign()
  after.signup_deadline = {month_end_offset_days:2,hour:17,minute:0,month_offset:-1}
  expect(campaignPatch(before,after)).toEqual({signup_deadline:after.signup_deadline})
 })
})

describe('reminder overview timing', () => {
  it('shows the nearest future unsent occurrence for the selected message and audience', () => {
    const schedule = [
      {id:'later',message_id:'signup',variant:'main',run_at:'2026-11-20T12:00:00Z'},
      {id:'other',message_id:'signup',variant:'lazy',run_at:'2026-11-19T12:00:00Z'},
      {id:'sent',message_id:'signup',variant:'main',run_at:'2026-11-19T12:00:00Z',status:'sent'},
      {id:'first',message_id:'signup',variant:'main',run_at:'2026-11-18T12:00:00Z'},
    ]
    expect(nextReminderOccurrence(schedule,'signup','main',Date.parse('2026-11-17T00:00:00Z'))?.id).toBe('first')
    expect(nextReminderOccurrence(schedule,'signup','main',Date.parse('2026-11-21T00:00:00Z'))).toBeUndefined()
  })
})
