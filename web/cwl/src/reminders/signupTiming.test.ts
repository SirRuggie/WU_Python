import { describe, expect, it } from 'vitest'
import { timingDate } from './signupTiming'
describe('signup dates', () => {
  it('shows existing month offsets as actual calendar dates without changing the rule', () => {
    const rule={mode:'monthly',day:23,hour:0,minute:30,month_offset:-1}
    expect(timingDate(rule,'2026-01','America/New_York')).toBe('2025-12-23T00:30')
    expect(rule.month_offset).toBe(-1)
  })
  it('handles short months, leap years and month-end rules', () => {
    expect(timingDate({month_end_offset_days:1,hour:17},'2028-02','UTC')).toBe('2028-02-28T17:00')
    expect(timingDate({mode:'monthly',day:31},'2026-02','UTC')).toBe('2026-02-28T17:00')
    expect(timingDate({mode:'monthly',day:31,missing_day:'skip'},'2026-02','UTC')).toBe('')
  })
  it('converts absolute timestamps to the campaign timezone rather than browser time', () => {
    expect(timingDate('2026-10-23T04:30:00Z','2026-10','America/New_York')).toBe('2026-10-23T00:30')
    expect(timingDate({mode:'specific',at:'2026-10-23T00:30'},'2026-10','America/New_York')).toBe('2026-10-23T00:30')
  })
  it('preserves empty input and does not invent dates for manual or relative rules', () => {
    expect(timingDate({at:''},'2026-10','UTC')).toBe('')
    expect(timingDate({mode:'manual'},'2026-10','UTC')).toBe('')
    expect(timingDate({mode:'after_open',offset_minutes:1440},'2026-10','UTC')).toBe('')
  })
})
