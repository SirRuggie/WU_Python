import {describe,it,expect} from 'vitest'
import {memberTarget, memberPath, loginPath} from './memberLinks'
describe('member page links',()=>{
 it('opens signup and assignment links with a season',()=>{
  expect(memberTarget('?view=signups&season=12')).toEqual({view:'signup',season:''})
  expect(memberPath('assignments','12')).toBe('/assignments')
 })
 it('keeps the target during sign-in and retry without browser storage',()=>{
  expect(loginPath('?view=signup&season=12',true)).toBe('/api/cwl/auth/discord?view=signup&retry=1')
  expect(loginPath('?view=todo',false)).toBe('/api/cwl/auth/discord?view=todo')
 })
 it('rejects external destinations and strips unrelated data',()=>{
  expect(memberTarget('?view=https://evil.test&season=12')).toEqual({view:'home',season:''})
  expect(memberPath('signup','bad')).toBe('/signup')
  expect(memberTarget('?view=todo&season=12')).toEqual({view:'todo',season:''})
 })
})

it('preserves everyday destinations through sign-in without accepting arbitrary redirects', () => {
  for (const view of ['search','wars','events']) {
    expect(memberTarget(`?view=${view}`).view).toBe(view)
    expect(loginPath(`?view=${view}`, false)).toBe(`/api/cwl/auth/discord?view=${view}`)
  }
  expect(memberTarget('?view=https://evil.example').view).toBe('home')
})

it('preserves the clean signup destination through sign-in', () => {
 expect(memberTarget('', '/signup')).toEqual({view:'signup', season:''})
 expect(loginPath('', false, '/signup')).toBe('/api/cwl/auth/discord?view=signup')
})

it('returns staff to Clan Weights after login without accepting arbitrary redirects',()=>{
 expect(loginPath('',false,'/clan-weights')).toBe('/api/cwl/auth/discord?view=weight-trial')
 expect(loginPath('?view=weight-trial',false)).toBe('/api/cwl/auth/discord?view=weight-trial')
 expect(loginPath('?view=https://evil.test',false)).toBe('/api/cwl/auth/discord?view=home')
})

it('opens saved signups directly and keeps the enabled member season',()=>{
 for(const [query,path] of [['','/my-signups'],['','/my-signups/'],['?view=my-signups&season=999','/'],['?tab=saved','/signup']]) {
  expect(memberTarget(query,path)).toEqual({view:'signup',season:'',signupPanel:'saved'})
  expect(loginPath(query,false,path)).toBe('/api/cwl/auth/discord?view=my-signups')
 }
 expect(loginPath('?view=weight-trial',false,'/tasks')).toBe('/api/cwl/auth/discord?view=todo')
})
