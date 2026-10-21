import {expect, it} from 'vitest'
import {unsignedAccounts, reconcileNewSignupDraft, selectedEntries, submittedSummary, clearSubmittedDraft} from './signup'
import type {Account, Signup} from './api'
const accounts = ['#ONE','#TWO','#THREE'].map(tag => ({tag,name:tag, town_hall:16,current_clan_tag:null,current_clan_name:null,verified:true,lazy_eligible:true,lazy_ineligible_reason:null,family_clan_status:'approved'} as Account))
const signups: Signup[] = [
  {tag:'#ONE',user_id:'123',pool:'main',prefer_crystal_1_or_lower:false},
  {tag:'#TWO',user_id:'123',pool:'lazy',prefer_crystal_1_or_lower:false},
]
it('hides all saved signups, regardless of pool or staff placement', () => {
  expect(unsignedAccounts(accounts,signups).map(account => account.tag)).toEqual(['#THREE'])
  expect(unsignedAccounts(accounts,[])).toEqual(accounts)
})
it('drops accounts signed up elsewhere or unlinked while retaining unsaved preferences', () => {
  const draft = {'#ONE':true,'#TWO':false,'#THREE':true,'#UNLINKED':true}
  expect(reconcileNewSignupDraft(draft,accounts,signups)).toEqual({'#THREE':true})
  expect(selectedEntries(unsignedAccounts(accounts,signups),draft)).toEqual([{tag:'#THREE',prefer_crystal_1_or_lower:true}])
})
it('preserves selected preferences in the saved summary', () => {
  expect(submittedSummary(accounts, [{tag:'#THREE',prefer_crystal_1_or_lower:true}])).toEqual([{tag:'#THREE',name:'#THREE',prefer_crystal_1_or_lower:true}])
})
it('clears only the submitted pool draft', () => {
  expect(clearSubmittedDraft({main:{'#ONE':false},lazy:{'#TWO':true}},'main')).toEqual({main:{},lazy:{'#TWO':true}})
})
