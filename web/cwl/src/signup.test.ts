import { describe, expect, it } from 'vitest'
import { reconcileSelection, accountPool, clearSubmittedDraft, seedDraft, selectAllAvailable, selectable, selectedEntries, selectedForPool, submittedSummary, transferSource } from './signup'
import type { Account, Signup } from './api'
const accounts: Account[] = [
  { tag: '#ONE', name: 'One', town_hall: 16, current_clan_tag: null, current_clan_name: null, verified: true, lazy_ineligible_reason: null, lazy_eligible: true, family_clan_status: 'approved' },
  { tag: '#TWO', name: 'Two', town_hall: 15, current_clan_tag: null, current_clan_name: null, verified: true, lazy_ineligible_reason: null, lazy_eligible: false, family_clan_status: 'outside' },
]
const signups: Signup[] = [{ tag: '#ONE', user_id: '123', pool: 'main', prefer_crystal_1_or_lower: false }]
describe('signup selection', () => {
  it('requires explicit transfer consent for the same account in another pool', () => {
    expect(accountPool(signups, '#ONE')).toBe('main')
    expect(transferSource(signups, '#ONE', 'lazy')).toBe('main')
    expect(selectable(accounts[0], 'lazy', signups)).toBe(false)
    expect(selectedForPool(accounts, { '#ONE': true }, signups, 'lazy', {})).toEqual([])
    expect(selectedForPool(accounts, { '#ONE': true }, signups, 'lazy', { '#ONE': 'main' })).toEqual([{ tag: '#ONE', prefer_crystal_1_or_lower: true, move_from_pool: 'main' }])
  })
  it('Select all never stages a cross-pool transfer', () => {
    expect(selectAllAvailable(accounts, 'lazy', signups, {}, {})).toEqual({ '#TWO': false })
    expect(selectAllAvailable(accounts, 'lazy', signups, { '#ONE': true }, { '#ONE': 'main' })).toEqual({ '#ONE': true, '#TWO': false })
  })
  it('allows outside and unknown family-clan status in either pool', () => {
    expect(selectable(accounts[1], 'lazy', signups)).toBe(true)
    expect(selectable({ ...accounts[1], family_clan_status: 'unknown' }, 'main', signups)).toBe(true)
  })
  it('allows linked accounts without verification in both pools', () => { expect(selectable({ ...accounts[1], verified: false }, 'main', signups)).toBe(true); expect(selectable({ ...accounts[1], verified: false }, 'lazy', signups)).toBe(true) })
  it('submits each selected tag once with its preference', () => { expect(selectedEntries(accounts, { '#ONE': true, '#TWO': false })).toEqual([{ tag: '#ONE', prefer_crystal_1_or_lower: true }, { tag: '#TWO', prefer_crystal_1_or_lower: false }]) })
  it('keeps transfer details in the completion summary and clears selection', () => {
    const payload = [{ tag: '#ONE', prefer_crystal_1_or_lower: true, move_from_pool: 'main' as const }]
    expect(submittedSummary(accounts, payload)).toEqual([{ tag: '#ONE', name: 'One', prefer_crystal_1_or_lower: true, move_from_pool: 'main' }])
    expect(clearSubmittedDraft({ main: { '#TWO': false }, lazy: { '#ONE': true } }, 'lazy')).toEqual({ main: { '#TWO': false }, lazy: {} })
  })
  it('can seed one explicit saved preference for editing', () => { expect(seedDraft(accounts, signups, 'main')).toEqual({ '#ONE': false }) })
})

describe('refreshing a member signup selection', () => {
  it('preserves ordinary selections while adding newly linked accounts', () => {
    expect(reconcileSelection({'#ONE':false}, {}, accounts, [], 'main')).toEqual({draft:{'#ONE':false},transfers:{}})
  })
  it('removes an account that is no longer linked', () => {
    expect(reconcileSelection({'#MISSING':false,'#ONE':true}, {}, accounts, [], 'main').draft).toEqual({'#ONE':true})
  })
  it('requires new consent when a saved account changes pool externally', () => {
    const saved = [{tag:'#ONE',pool:'lazy',user_id:'1',prefer_crystal_1_or_lower:false}] as Signup[]
    expect(reconcileSelection({'#ONE':false}, {}, accounts, saved, 'main').draft).toEqual({})
    expect(reconcileSelection({'#ONE':false}, {'#ONE':'lazy'}, accounts, saved, 'main')).toEqual({draft:{'#ONE':false},transfers:{'#ONE':'lazy'}})
    expect(reconcileSelection({'#ONE':false}, {'#ONE':'lazy'}, accounts, [], 'main').draft).toEqual({})
  })
})
