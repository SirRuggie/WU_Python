import {describe, it, expect} from 'vitest'
import {comparisonLocation, type ComparisonLocation} from './comparisonLocation'
const now = Date.now()
const location: ComparisonLocation = {current_clan_tag:'#A',current_clan_name:'Clan A',current_clan_checked_at:new Date(now).toISOString(),arrival_status:'arrived'}
describe('comparison clan location', () => {
  it('compares physical location with the column even after a swap', () => {
    expect(comparisonLocation(location,'#A',now).state).toBe('arrived')
    expect(comparisonLocation(location,'#B',now).state).toBe('missing')
  })
  it('does not claim arrival for missing, stale, failed, or in-flight checks', () => {
    expect(comparisonLocation(undefined,'#A',now).state).toBe('unknown')
    expect(comparisonLocation(location,'#A',now+121000).state).toBe('unknown')
    expect(comparisonLocation({...location,arrival_status:'unknown'},'#A',now).state).toBe('unknown')
    expect(comparisonLocation({...location,location_updating:true},'#A',now).state).toBe('unknown')
  })
  it('treats a checked account without a clan as not arrived', () => {
    expect(comparisonLocation({...location,current_clan_tag:null,current_clan_name:null},'#A',now).state).toBe('missing')
  })
})
