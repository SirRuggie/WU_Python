import { describe, expect, it } from 'vitest'
import { addReminderTime, timeLabel } from './types'

describe('custom reminder schedule inputs', () => {
  it('accepts fractional hours that resolve to whole minutes and removes duplicates', () => {
    expect(addReminderTime([60, 720], '1.25', 60)).toEqual([720, 75, 60])
    expect(addReminderTime([60, 720], '1', 60)).toEqual([720, 60])
  })
  it.each(['', ' ', 'NaN', 'Infinity', '-1', '0', '1441', '1.5'])('rejects invalid minute input %s', amount => {
    expect(() => addReminderTime([], amount, 1)).toThrow()
  })
  it('labels custom times without dropping minutes', () => {
    expect(timeLabel(75)).toBe('1h 15m')
    expect(timeLabel(30)).toBe('30m')
    expect(timeLabel(720)).toBe('12h')
  })
})
