import { describe, expect, it } from 'vitest'
import { clanSummary, compareClanAccounts, comparisonOrder, moveComparisonClan } from './compare'
import type { RosterAccount } from './roster'
const basic = (tag: string, clan: string, townHall: number | null, weight: number | null): RosterAccount => ({ tag, assigned_clan_tag: clan, town_hall: townHall, effective_weight: weight, user_id: '1', pool: 'main', player_name: tag, prefer_crystal_1_or_lower: false, source_weight: weight, source_status: 'current', source_name: null, source_checked_at: null, source_modified_at: null, manual_weight: null, kept: true })
const accounts = [basic('#A', '#ONE', 16, 175000), basic('#B', '#ONE', null, null), basic('#C', '#ONE', 14, 165000), basic('#D', '#TWO', 12, 150000)]
describe('clan comparison', () => {
  it('summarizes occupancy, average TH and total known weight within each clan', () => { expect(clanSummary(accounts, '#ONE')).toEqual({ count: 3, knownTownHalls: 2, averageTownHall: 15, knownWeights: 2, totalWeight: 340000 }); expect(clanSummary(accounts, '#EMPTY').totalWeight).toBeNull() })
  it('sorts each clan without moving missing numeric values to the top', () => { expect(compareClanAccounts(accounts, '#ONE', 'town_hall_desc').map(item => item.tag)).toEqual(['#A', '#C', '#B']); expect(compareClanAccounts(accounts, '#ONE', 'weight_asc').map(item => item.tag)).toEqual(['#C', '#A', '#B']) })
})

it('preserves chosen order and empty choices; removes archived clans without filling unwanted columns',()=>{
 expect(comparisonOrder(['#B','#A','#B','#OLD'],['#A','#B','#C'])).toEqual(['#B','#A'])
 expect(comparisonOrder([],['#A','#B'])).toEqual([])
 expect(comparisonOrder(null,['#A','#B'])).toEqual(['#A','#B'])
 expect(comparisonOrder(['#B'],['#A','#B','#NEW'])).toEqual(['#B'])
})
it('moves a clan next to another without dropping hidden clans or creating duplicates',()=>{
 expect(moveComparisonClan(['#A','#HIDDEN','#B'],'#A','#B')).toEqual(['#B','#HIDDEN','#A'])
 expect(moveComparisonClan(['#A','#B'],'#A',undefined)).toEqual(['#A','#B'])
})
