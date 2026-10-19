import {expect,it} from 'vitest'
import {matchesLeague,matchesTownHall} from './ClanFilters'
it('combines selected leagues and town halls without mislabeling unknowns',()=>{
 expect(matchesLeague('Crystal League I',[])).toBe(true)
 expect(matchesLeague('Crystal League I',['Gold League I'])).toBe(false)
 expect(matchesLeague(null,['Unranked'])).toBe(false)
 expect(matchesLeague(null,['League unavailable'])).toBe(true)
 expect(matchesTownHall(18,['TH 17','TH 18'])).toBe(true)
 expect(matchesTownHall(16,['TH 17','TH 18'])).toBe(false)
 expect(matchesTownHall(null,['TH 18'])).toBe(false)
 expect(matchesTownHall(null,['Unknown TH'])).toBe(true)
})
