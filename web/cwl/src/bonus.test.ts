import { describe, expect, it } from 'vitest'
import { pageItems, parseNullableWhole, selectionReasonError, selectionsChanged, selectionsFromAccounts, selectionsPayload, type BonusAccount } from './bonus'
const row = (tag: string, selected: boolean, recommended: boolean | null, reason = ''): BonusAccount => ({ tag, player_name: tag, pool: 'main', assigned_clan_tag: '#HOST', assigned_clan_name: 'Host', attacks: null, stars: 0, source_status: 'partial', source_warning: null, source_complete: false, already_confirmed_this_cycle: false, last_confirmed_bonus: null, recommended, eligibility_reason: null, selected, reason })
describe('bonus selection review', () => {
  it('allows an incomplete draft so the server preview can explain required reasons', () => {
    const accounts = [row('#A', false, null), row('#B', false, true)]
    expect(selectionReasonError(accounts, { '#A': '' })).toBeNull()
    expect(selectionReasonError(accounts, { '#A': 'Staff review' })).toBeNull()
    expect(selectionReasonError(accounts, { '#B': '' })).toBeNull()
    expect(selectionReasonError([{ ...accounts[1], source_complete: true, source_status: 'complete' }], { '#B': '' })).toBeNull()
  })
  it('replaces the whole draft with sorted selected tags and detects unsaved changes', () => {
    const accounts = [row('#A', true, null, 'manual'), row('#B', false, true)]
    expect(selectionsFromAccounts(accounts)).toEqual({ '#A': 'manual' })
    expect(selectionsChanged(accounts, { '#A': 'manual' })).toBe(false)
    expect(selectionsChanged(accounts, { '#A': 'manual', '#B': '' })).toBe(true)
    expect(selectionsPayload({ '#B': '  reason  ', '#A': '' })).toEqual([{ tag: '#A', reason: '' }, { tag: '#B', reason: 'reason' }])
  })
  it('preserves unset rules separately from zero and paginates candidates', () => {
    expect(parseNullableWhole('', 0, 7)).toBeNull()
    expect(parseNullableWhole('0', 0, 7)).toBe(0)
    expect(parseNullableWhole('8', 0, 7)).toBeUndefined()
    expect(pageItems(Array.from({ length: 10 }, (_, i) => i), 1)).toEqual([8, 9])
  })
})
