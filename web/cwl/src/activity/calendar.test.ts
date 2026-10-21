import {expect,it} from 'vitest'
import {gameCalendar,localTime,countdown} from './calendar'
const event = (id:string, time:string) => gameCalendar(Date.parse(time)).find(item=>item.id===id)!
it('opens and closes raid weekends at UTC boundaries',()=>{
  expect(event('raid','2026-10-23T06:59:59Z').start).toBe(Date.parse('2026-10-23T07:00:00Z'))
  expect(event('raid','2026-10-26T06:59:59Z').end).toBe(Date.parse('2026-10-26T07:00:00Z'))
  expect(event('raid','2026-10-26T07:00:00Z').start).toBe(Date.parse('2026-10-30T07:00:00Z'))
})
it('rolls monthly dates across December and leap February',()=>{
  expect(event('games','2026-12-28T08:00:00Z').start).toBe(Date.parse('2027-01-22T08:00:00Z'))
  expect(event('games','2028-02-29T12:00:00Z').start).toBe(Date.parse('2028-03-22T08:00:00Z'))
  expect(event('cwl','2026-11-03T08:00:00Z').start).toBe(Date.parse('2026-12-01T08:00:00Z'))
})
it('uses a 28-day league cycle rather than last Monday of the month',()=>{
  const season=event('season','2026-10-21T12:00:00Z')
  expect(season.start).toBe(Date.parse('2026-10-05T05:00:00Z'))
  expect(season.end).toBe(Date.parse('2026-11-02T05:00:00Z'))
  expect(event('season','2026-11-02T05:00:00Z').start).toBe(season.end)
})
it('formats each date in its own DST offset and never gives a negative countdown',()=>{
  expect(localTime(Date.parse('2026-10-05T05:00:00Z'),'America/New_York')).toContain('1:00')
  expect(localTime(Date.parse('2026-11-02T05:00:00Z'),'America/New_York')).toContain('12:00')
  expect(countdown(0,60000)).toBe('now')
  expect(countdown(90*60000,0)).toBe('1 hour 30m')
})
