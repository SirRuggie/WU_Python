import { describe, expect, it } from 'vitest'
import { canApply, clanKey, scheduleValues, type ReturnClan } from './model'
const row = (section: 'MAIN'|'FWA', state: string) => ({id:section+'#P0',label:'Example',return_status:{state}} as ReturnClan)
describe('return controls', () => {
  it('keeps Main manual and rejects missing or expired lists', () => {
    for(const action of ['schedule','start','resume','pause'] as const) expect(canApply(row('MAIN','manual'),action)).toBe(false)
    expect(canApply(row('MAIN','manual'),'send')).toBe(true)
    expect(canApply(row('FWA','not_saved'),'save')).toBe(true)
    expect(canApply(row('FWA','expired'),'schedule')).toBe(false)
    expect(clanKey(row('FWA','idle'))).toBe('FWA:#P0')
  })
  it('rejects incomplete, reversed, and overlong dates', () => {
    expect(() => scheduleValues('','')).toThrow()
    expect(() => scheduleValues('2099-01-03T12:00','2099-01-01T12:00')).toThrow()
    expect(() => scheduleValues('2099-01-01T12:00','2099-01-09T12:00')).toThrow()
    const dates = scheduleValues('2099-01-01T12:00','2099-01-03T12:00')
    expect(new Date(dates.schedule_end).getTime()-new Date(dates.schedule_start).getTime()).toBe(2*86400000)
  })
})
