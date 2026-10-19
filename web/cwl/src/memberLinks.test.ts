import {describe,it,expect} from 'vitest'
import {memberTarget, memberPath, loginPath} from './memberLinks'
describe('member page links',()=>{
 it('opens signup and assignment links with a season',()=>{
  expect(memberTarget('?view=signups&season=12')).toEqual({view:'signup',season:'12'})
  expect(memberPath('assignments','12')).toBe('/?view=assignments&season=12')
 })
 it('keeps the target during sign-in and retry without browser storage',()=>{
  expect(loginPath('?view=signup&season=12',true)).toBe('/api/cwl/auth/discord?view=signup&season=12&retry=1')
  expect(loginPath('?view=todo',false)).toBe('/api/cwl/auth/discord?view=todo')
 })
 it('rejects external destinations and strips unrelated data',()=>{
  expect(memberTarget('?view=https://evil.test&season=12')).toEqual({view:'home',season:''})
  expect(memberPath('signup','bad')).toBe('/?view=signup')
  expect(memberTarget('?view=todo&season=12')).toEqual({view:'todo',season:''})
 })
})
