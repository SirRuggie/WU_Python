import { describe, expect, it } from 'vitest'
import { attacksText, type RaffleAccount } from './bonusRaffle'

describe('bonus participation display', () => {
  it('shows the actual season round count without inventing seven rounds', () => {
    expect(attacksText({ attacks: 5, season_rounds: 7 } as RaffleAccount)).toBe('5/7 attacks')
    expect(attacksText({ attacks: 4, season_rounds: 5 } as RaffleAccount)).toBe('4/5 attacks')
    expect(attacksText({ attacks: 5 } as RaffleAccount)).toBe('5 attacks')
  })
  it('distinguishes unavailable totals, zero attacks and staff corrections', () => {
    expect(attacksText({ attacks: null } as RaffleAccount)).toBe('Not Available')
    expect(attacksText({ attacks: 0, season_rounds: 7 } as RaffleAccount)).toBe('0/7 attacks')
    expect(attacksText({ attacks: 5, attacks_override: true } as RaffleAccount)).toBe('5 attacks · Staff correction')
  })
})

describe('bonus review status', () => {
  it('does not call an unchecked candidate eligible before preview', async () => {
    const { bonusCandidateStatus } = await import('./bonusRaffle')
    const account = { player_name: 'Example', tag: '#ABC', attacks: 4 } as RaffleAccount
    expect(bonusCandidateStatus(account, 'candidates')).toBe('')
    expect(bonusCandidateStatus(account, 'eligible')).toBe('')
  })
  it('keeps exclusions and saved cooldown visible', async () => {
    const { bonusCandidateStatus } = await import('./bonusRaffle')
    const account = { exclusion: 'Missed sync', three_cycle_cooldown: true } as RaffleAccount
    expect(bonusCandidateStatus(account, 'excluded')).toBe('Missed sync')
    expect(bonusCandidateStatus({ three_cycle_cooldown: true } as RaffleAccount, 'candidates')).toContain('sit out this season')
  })
  it('labels a staff exception and a saved winner distinctly', async () => {
    const { bonusCandidateStatus } = await import('./bonusRaffle')
    const account = { bonus_review: { flags: ['left_family'], override_reason: 'Staff exception' } } as RaffleAccount
    expect(bonusCandidateStatus(account, 'eligible')).toBe('Included by staff exception')
    expect(bonusCandidateStatus(account, 'winners')).toBe('')
  })
})

describe('bonus draw review gate', () => {
  it('keeps a reviewed draw unavailable while any local editor or blocking check is active', async () => {
    const { canSaveBonusDraw } = await import('./bonusRaffle')
    const ready = { canManage: true, busy: false, archived: false, policyDirty: false,
      roleDirty: false, reviewDirty: false, reviewOpen: false, candidateOpen: false,
      lookingUp: false, blocked: false }
    expect(canSaveBonusDraw(ready)).toBe(true)
    for (const key of ['policyDirty', 'roleDirty', 'reviewDirty', 'reviewOpen', 'candidateOpen', 'lookingUp', 'blocked', 'busy', 'archived'] as const) {
      expect(canSaveBonusDraw({ ...ready, [key]: true })).toBe(false)
    }
    expect(canSaveBonusDraw({ ...ready, canManage: false })).toBe(false)
  })
})
