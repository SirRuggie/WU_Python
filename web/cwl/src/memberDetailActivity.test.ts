import { describe, expect, it } from 'vitest'
import { activityState, matchingWarActivity, ownAttackText } from './memberDetailActivity'

const account = (tag: string, attacks_left: number, attacks_total = 2) => ({ tag, attacks_left, attacks_total })

describe('member war activity projection', () => {
  it('keeps only the requested player attacks in the current clan regular war', () => {
    const result = matchingWarActivity({ clans: [
      { tag: '#CLAN1', name: 'Home', accounts: [{tag: '#AAA111'}], regular: { state: 'inWar', my_accounts: [account('#AAA111', 1), account('#BBB222', 2)] } },
      { tag: '#CLAN2', name: 'Other', accounts: [{tag: '#AAA111'}], regular: { state: 'inWar', my_accounts: [account('#AAA111', 0)] } },
    ] }, 'player', '#AAA111', '#CLAN1')
    expect(result?.regular?.my_accounts).toEqual([account('#AAA111', 1)])
    expect(result?.regularClan).toEqual({tag: '#CLAN1', name: 'Home'})
    expect(ownAttackText(result?.regular || null, '#AAA111')).toBe('1/2 attacks used')
  })

  it('keeps regular war current while independently finding recent CWL on a hosting clan', () => {
    const result = matchingWarActivity({ clans: [
      { tag: '#HOME01', name: 'Home Clan', accounts: [{tag: '#AAA111'}], regular: { state: 'none' }, cwl: { state: 'none' } },
      { tag: '#HOST01', name: 'CWL Host', accounts: [], cwl: { state: 'inWar', my_accounts: [account('#AAA111', 0), account('#BBB222', 1)] } },
    ] }, 'player', '#AAA111', '#HOME01')
    expect(result?.regular?.state).toBe('none')
    expect(result?.regularClan?.tag).toBe('#HOME01')
    expect(result?.cwl?.my_accounts).toEqual([account('#AAA111', 0)])
    expect(result?.cwlClan).toEqual({tag: '#HOST01', name: 'CWL Host'})
  })

  it('does not borrow another account’s CWL and preserves private or error status for the current clan', () => {
    const result = matchingWarActivity({ clans: [
      { tag: '#HOME01', name: 'Home', accounts: [{tag: '#AAA111'}], regular: { state: 'private' }, cwl: { state: 'error' } },
      { tag: '#HOST01', name: 'Host', accounts: [], cwl: { state: 'inWar', my_accounts: [account('#BBB222', 0)] } },
    ] }, 'player', '#AAA111', '#HOME01')
    expect(result?.regular?.state).toBe('private')
    expect(result?.cwl?.state).toBe('error')
    expect(result?.regularClan?.tag).toBe('#HOME01')
    expect(result?.cwlClan?.tag).toBe('#HOME01')
  })

  it('selects only the requested clan and preserves valid freshness and a concise warning', () => {
    const result = matchingWarActivity({ checked_at: '2026-10-26T12:00:00Z', warnings: ['One account could not be checked.'], clans: [
      { tag: '#OTHER1', regular: { state: 'inWar' } },
      { tag: '#CLAN1', name: 'The Clan', regular: { state: 'preparation', clan: { stars: 0, destruction: 0 } }, cwl: { state: 'private' } },
    ] }, 'clan', '#CLAN1')
    expect(result?.regular?.state).toBe('preparation')
    expect(result?.cwl?.state).toBe('private')
    expect(result?.regularClan).toEqual({tag: '#CLAN1', name: 'The Clan'})
    expect(result?.checkedAt).toBe('2026-10-26T12:00:00.000Z')
    expect(result?.warning).toContain('One account')
  })

  it('treats null, malformed, and absent rows as no activity returned, not no war', () => {
    expect(matchingWarActivity(null, 'clan', '#CLAN1')).toBeNull()
    expect(matchingWarActivity({ clans: [] }, 'clan', '#CLAN1')).toBeNull()
    expect(matchingWarActivity({ clans: [{ tag: '<img>', regular: { state: 'none' } }] }, 'clan', '#CLAN1')).toBeNull()
    expect(activityState(null)).toBe('War details are unavailable.')
    expect(activityState({ state: 'private' })).toBe('War details are private.')
    expect(activityState({ state: 'none' })).toBe('No war returned.')
    expect(activityState({ state: 'warEnded' })).toBe('War ended.')
    expect(activityState({ state: 'awaitingResult' })).toBe('War ended · results pending')
  })

  it('labels active lineup absence only when a lineup was actually returned', () => {
    expect(ownAttackText({ state: 'inWar', my_accounts: [] }, '#AAA111')).toBe('This account is not listed in this war.')
    expect(ownAttackText({ state: 'preparation', my_accounts: [account('#BBB222', 1)] }, '#AAA111')).toBe('This account is not listed in this war.')
    expect(ownAttackText({ state: 'inWar' }, '#AAA111')).toBeNull()
    expect(ownAttackText({ state: 'error' }, '#AAA111')).toBeNull()
    const result = matchingWarActivity({ clans: [{ tag: '#HOME01', accounts: [{tag: '#AAA111'}], regular: { state: 'inWar' } }] }, 'player', '#AAA111', '#HOME01')
    expect(result?.regular?.my_accounts).toBeUndefined()
    expect(ownAttackText(result?.regular || null, '#AAA111')).toBeNull()
  })

  it('rejects malformed or impossible attack counters and invalid timestamps', () => {
    expect(matchingWarActivity({ checked_at: 'yesterdayish', clans: [{ tag: '#CLAN1', accounts: [{tag: '#AAA111'}], regular: { state: 'inWar', my_accounts: [{ tag: null, attacks_left: 0, attacks_total: 2 }] } }] }, 'player', '#AAA111', '#CLAN1')?.checkedAt).toBeNull()
    for (const [attacks_left, attacks_total] of [[-1, 2], [3, 2], [Number.NaN, 2], [0, Number.POSITIVE_INFINITY], [1.5, 2]]) {
      expect(ownAttackText({ state: 'inWar', my_accounts: [{ tag: '#AAA111', attacks_left, attacks_total }] }, '#AAA111')).toBe('Attack count unavailable.')
    }
    expect(ownAttackText({ state: 'inWar', my_accounts: [{ tag: '#AAA111', attacks_left: '0', attacks_total: 2 }] }, '#AAA111')).toBe('Attack count unavailable.')
  })
})
