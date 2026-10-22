import { describe, expect, it } from 'vitest'
import { manualWeightDraft, manualWeightFields, parseManualWeight } from './manualWeight'

describe('manual roster weight entry', () => {
  it('converts loot to full weight without a thousands multiplier', () => {
    const draft = { unit: 'loot' as const, text: '25,000' }
    expect(parseManualWeight(draft)).toBe(125000)
    expect(manualWeightFields(draft)).toEqual({ loot: '25,000', full: '125000' })
  })
  it('accepts full weight and preserves saved weights exactly', () => {
    for (const weight of [1, 149000, 174501, 500000]) {
      const draft = manualWeightDraft(weight)
      expect(parseManualWeight(draft)).toBe(weight)
      expect(Number(manualWeightFields(draft).loot)).toBe(weight / 5)
    }
  })
  it('can switch fields without multiplying twice', () => {
    const fields = manualWeightFields({ unit: 'loot', text: '29800' })
    expect(parseManualWeight({ unit: 'full', text: fields.full })).toBe(149000)
    expect(manualWeightFields({ unit: 'full', text: '150000' }).loot).toBe('30000')
  })
  it('clears both fields to restore source weight', () => {
    for (const unit of ['loot', 'full'] as const) {
      expect(parseManualWeight({ unit, text: '' })).toBeNull()
      expect(manualWeightFields({ unit, text: '' })).toEqual({ loot: '', full: '' })
    }
  })
  it('keeps bad input visible and refuses invalid saves', () => {
    for (const text of ['-1', '0', 'Infinity', '1e4', '149k', '100001', '1.01']) {
      const draft = { unit: 'loot' as const, text }
      expect(() => parseManualWeight(draft)).toThrow()
      expect(manualWeightFields(draft)).toEqual({ loot: text, full: '' })
    }
    expect(() => parseManualWeight({ unit: 'full', text: '149000.5' })).toThrow()
  })
})
