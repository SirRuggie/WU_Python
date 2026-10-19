import {describe,it,expect} from 'vitest'
import {sortClans} from './clanSort'
describe('clan league sorting',()=>{
  const clans=['Unranked','Crystal League III','Champion League I','Crystal League I','Bronze League III',null].map((cwl_league,index)=>({tag:String(index),name:String(index),cwl_league}))
  it('orders tiers and divisions correctly with unranked and unavailable last',()=>{
    expect(sortClans(clans,'league_desc').map(c=>c.cwl_league)).toEqual(['Champion League I','Crystal League I','Crystal League III','Bronze League III','Unranked',null])
    expect(sortClans(clans,'league_asc').map(c=>c.cwl_league)).toEqual(['Bronze League III','Crystal League III','Crystal League I','Champion League I','Unranked',null])
    expect(clans[0].cwl_league).toBe('Unranked')
  })
  it('breaks same-league ties by name',()=>{
    expect(sortClans([{tag:'1',name:'Z',cwl_league:'Gold League I'},{tag:'2',name:'A',cwl_league:'Gold League I'}],'league_desc')[0].name).toBe('A')
  })
})
