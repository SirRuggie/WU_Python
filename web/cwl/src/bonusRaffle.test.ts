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
